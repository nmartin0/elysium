"""
pending_write_store.py  (in-memory store for writes awaiting human
confirmation over HTTP)

Exists specifically for the propose/confirm split -- see api/routes.py's
docstring for why this can't be a single blocking call the way
scripts/run_deployment.py's terminal confirm_write is: the propose and
confirm steps are genuinely two separate HTTP requests, possibly
minutes apart, and something has to hold the proposed write in between.

REAL, STATED LIMITATION: this is in-process memory, not a database --
works correctly for exactly the single-worker deployment
install/elysium.service already runs (uvicorn api.app:app, no
--workers flag). A future multi-process deployment would need a
shared store instead; a confirmation routed to a different worker
process than the one that handled the proposal would find nothing
here. Flagged now, not discovered later.

AND THE CONSEQUENCE FOR TESTING BY HAND, which the paragraph above
implies without saying: a RESTART empties this store. Running uvicorn
with --reload restarts it on any watched file change, so editing
policy.yaml -- exactly what someone does to exercise an approvals flow
-- silently discards every pending proposal mid-test.

That cost a real debugging session: proposals kept vanishing between
steps and looked like a bug in the queue. Use --reload when editing
Python; do not use it while testing writes. Configuration changes need
no restart at all, and POST /api/admin/reload deliberately PRESERVES
this store.

Every stored write has a real TTL (DEFAULT_TTL) -- an unconfirmed
proposal doesn't linger forever. Expiry is LAZY (checked at the top of
store()/pop(), not a separate periodic background task) -- this is a
low-volume store; noticing an expired entry a little late, at the next
touch rather than on a fixed timer, costs nothing real, and avoids
needing a genuine asyncio background task (which would need a real
startup hook to launch correctly, adding real complexity for no
practical benefit at this volume). Every expiry found this way is
logged via audit_log.log_write_expired() -- a proposal that's abandoned
still leaves a real trace, not silent disappearance.

pop() is uniform-denial on purpose: wrong user, unknown ID, and
expired ID all return the SAME None -- same principle used everywhere
else in this project (see core/ontology/mediator.py's docstring).

audit_log is genuinely explicit here, not read back from a mediator
the way WriteMediator/AgentLoop now do (see their own audit_log
properties) -- this store has no mediator reference at all, nothing
to read one back from; defaults to a fresh AuditLog() (its own
class-level default path) the same way DataMediator itself does when
not given one explicitly, for the identical reason -- see AuditLog's
own module docstring.

Used by: api/app.py (one instance, stored on app.state, same lifecycle
         as everything else built once at startup), api/routes.py
"""

import threading
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from core.intermediate_layer.audit import AuditLog
from core.ontology.write_mediator import PendingWrite

DEFAULT_TTL = timedelta(minutes=15)


@dataclass
class _StoredWrite:
    pending: PendingWrite
    owner_user_id: str
    expires_at: datetime
    # Somebody is deciding on this RIGHT NOW. Set for the length of one
    # confirm request, so a second reviewer cannot reserve it and a
    # listing does not offer it. Cleared if the decision fails.
    reserved: bool = False


def _fingerprint(pending) -> tuple:
    """What makes two proposals the same proposal.

    THE CHANGE ITSELF: the action, and every object/operation/values
    triple it would apply. Not the proposer, not the description, not
    the time.

    Sorted, because sub_writes order is an implementation detail of how
    an action resolves and two identical proposals must not differ by
    it. json.dumps with sort_keys for the values, since a dict is not
    hashable and key order is equally incidental.
    """
    import json

    return (
        pending.action_type_name,
        tuple(sorted(
            (sub.object_type, str(sub.object_id), sub.operation,
             json.dumps(sub.changes, sort_keys=True, default=str))
            for sub in pending.sub_writes
        )),
    )


class PendingWriteStore:
    def __init__(self, ttl: timedelta = DEFAULT_TTL,
                 audit_log: AuditLog | Callable[[], AuditLog] | None = None):
        """`audit_log` may be an instance or a callable returning one.

        A CALLABLE because this store SURVIVES a configuration reload
        while the audit log does not: each generation builds its own,
        stamped with its own generation number. Holding an instance
        means a write expiring after a reload is recorded against the
        log object from STARTUP, so the entry names the wrong
        generation -- a wrong-but-plausible value in an audit trail,
        which is worse than an obviously missing one.

        Same shape as UserDirectory's roles, and the same reason: this
        is runtime state that carries a slice of configuration. See
        HOT_RELOAD_PLAN.md.

        Not yet load-bearing, since every generation's AuditLog writes
        to the same file. It becomes load-bearing the moment pending
        writes outlive several generations, which is exactly what an
        approvals inbox is for.
        """
        self._ttl = ttl
        self._audit_log = audit_log if audit_log is not None else AuditLog()
        self._lock = threading.Lock()
        self._writes: dict[str, _StoredWrite] = {}

    @property
    def audit_log(self) -> AuditLog:
        return self._audit_log() if callable(self._audit_log) else self._audit_log

    def _expire_stale_locked(self) -> None:
        # Called with self._lock already held.
        now = datetime.now(UTC)
        expired_ids = [write_id for write_id, stored in self._writes.items() if now >= stored.expires_at]
        for write_id in expired_ids:
            stored = self._writes.pop(write_id)
            self.audit_log.log_write_expired(write_id, stored.owner_user_id, stored.pending.description)

    def store(self, pending: PendingWrite) -> str:
        write_id = str(uuid.uuid4())
        expires_at = datetime.now(UTC) + self._ttl
        with self._lock:
            self._expire_stale_locked()
            self._writes[write_id] = _StoredWrite(pending, pending.user_id, expires_at)
        return write_id

    def awaiting(self, may_claim) -> list[tuple[str, PendingWrite]]:
        """Every unexpired write the caller may act on, id and all.

        THE SAME PREDICATE claim() takes, deliberately. A listing that
        decided eligibility differently from the claim would show writes
        that cannot be claimed, or hide ones that can -- and the second
        is worse, because an approver would never learn a decision was
        waiting for them.

        EXPIRES FIRST, so a listing never shows a write that would 404
        on the next request. A stale entry in an inbox is worse than an
        absent one: the reviewer spends attention on a decision that has
        already been taken away from them.

        RETURNS IDS, and that is the point -- before this, confirming a
        write required knowing its id, which only the proposer had. A
        four-eyes rule was enforceable and unreachable: the one person
        who could find the write was the one person forbidden to
        approve it.

        NOT SORTED HERE. Oldest-first is what an inbox wants, but that
        is a presentation choice and the caller has the timestamps.
        """
        with self._lock:
            self._expire_stale_locked()
            return [
                (write_id, stored.pending)
                for write_id, stored in self._writes.items()
                # A RESERVED WRITE IS HIDDEN. Somebody is deciding on
                # it right now, and a reservation lasts one request --
                # showing it would invite a second reviewer to open
                # something about to disappear. If the decision fails
                # it is released and reappears.
                if not stored.reserved and may_claim(stored.pending)
            ]

    def expires_at(self, write_id: str) -> str | None:
        """When a write stops being decidable, as an ISO timestamp.

        SEPARATE FROM awaiting(), because the expiry is the store's own
        bookkeeping rather than part of the write -- PendingWrite does
        not carry it, and adding it there would put a value that
        changes per storage into the object being stored.
        """
        with self._lock:
            stored = self._writes.get(write_id)
            return stored.expires_at.isoformat() if stored is not None else None

    @contextmanager
    def reserved(self, write_id: str, may_claim):
        """Holds a write while a decision is made, then commits or releases.

        WHY TWO PHASES. claim() removed the write and handed it back,
        and the decision could then FAIL -- a four-eyes rule refusing a
        self-approval, or a field the ontology no longer declares. The
        proposal was already gone. The colleague entitled to approve it
        never got the chance and nothing told them it had existed.

        Worse than losing a write, because the refusal is the system
        working correctly: every control built for this flow lands
        AFTER the point of no return.

        RESERVATION IS UNDER THE LOCK, so the atomicity claim() existed
        for survives: two approvers cannot both reserve one write, and
        the second sees exactly what an unknown id looks like.

        A CONTEXT MANAGER RATHER THAN THREE CALLS, because the release
        is the half that gets forgotten. An exception anywhere in the
        body -- a criteria violation, a database failure, a bug --
        puts the write back. Only a clean exit consumes it.

        A CRASH BETWEEN RESERVE AND COMMIT leaves a write reserved
        forever, which is why expiry still applies to reserved writes:
        the TTL is the backstop, and a stuck reservation resolves
        itself rather than needing a restart.
        """
        with self._lock:
            self._expire_stale_locked()
            stored = self._writes.get(write_id)
            if stored is None or stored.reserved or not may_claim(stored.pending):
                reserved = None
            else:
                self._writes[write_id] = replace(stored, reserved=True)
                reserved = stored.pending

        if reserved is None:
            yield None
            return

        committed = False
        try:
            yield reserved
            committed = True
        finally:
            with self._lock:
                still_there = self._writes.get(write_id)
                if still_there is None:
                    # Expired mid-decision. Nothing to commit or put
                    # back, and the expiry was already audited.
                    pass
                elif committed:
                    del self._writes[write_id]
                else:
                    self._writes[write_id] = replace(still_there, reserved=False)

    def duplicates_of(self, write_id: str) -> int:
        """How many OTHER pending writes propose the same change.

        SURFACED, NOT PREVENTED, and that distinction is the whole
        design. A second identical proposal might be a double-click, or
        a colleague re-requesting something forgotten, or a deliberate
        nudge -- and Elysium cannot tell which. Foundry allows
        duplicates too and relies on the reviewer seeing them together.

        What was actually wrong was that three identical rows were
        INDISTINGUISHABLE: same action, same object, same values, no
        way to tell one mistake pasted three times from three separate
        requests. A reviewer approving one left two behind with nothing
        explaining why.

        IDENTITY IS THE CHANGE, NOT THE PROPOSER. Two people
        independently proposing the same edit is the clearest case of a
        duplicate there is, and keying on the proposer would hide
        exactly that.

        Reserved writes are counted: somebody deciding on one right now
        does not make it a different proposal, and excluding it would
        make the count flicker during a decision.
        """
        with self._lock:
            self._expire_stale_locked()
            stored = self._writes.get(write_id)
            if stored is None:
                return 0
            fingerprint = _fingerprint(stored.pending)
            return sum(
                1 for other_id, other in self._writes.items()
                if other_id != write_id and _fingerprint(other.pending) == fingerprint
            )

    def claim(self, write_id: str, may_claim) -> PendingWrite | None:
        """Removes and returns a write, if the caller may act on it.

        THE PREDICATE RUNS UNDER THE LOCK, which is the whole reason
        this is a store method and not two calls. A caller that looked
        the write up, decided, and then popped it would leave a window
        in which two approvers both pass the check and both claim the
        same write -- and the second one applies a change that was
        already applied.

        WHO MAY CLAIM IS THE CALLER'S QUESTION, not this store's. It
        used to be answered here as owner-equality, which made
        four-eyes unreachable: the only person who could confirm a
        write was the one person a four-eyes rule forbids. Policy
        belongs where the grants and criteria live; atomicity belongs
        here.

        UNIFORM DENIAL IS PRESERVED BY CONSTRUCTION. Unknown id,
        expired id and ineligible caller all return None, and the
        caller cannot tell which -- the same property the old
        owner-equality check had, kept deliberately rather than
        rebuilt. A probing caller learns nothing about which write ids
        exist.
        """
        with self._lock:
            self._expire_stale_locked()
            stored = self._writes.get(write_id)
            if stored is None or not may_claim(stored.pending):
                return None
            del self._writes[write_id]
            return stored.pending
