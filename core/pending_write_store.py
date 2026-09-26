"""
pending_write_store.py  (writes awaiting human confirmation)

Exists for the propose/confirm split -- see api/routes.py's docstring
for why this cannot be one blocking call the way scripts/
run_deployment.py's terminal confirm_write is: propose and confirm are
two separate HTTP requests, possibly minutes apart, and something has
to hold the proposed write in between.

THE DATABASE IS THE STORE. Every read and write goes to SQLite; there
is no in-memory copy.

WHY, AND IT IS A CORRECTION. This module's docstring used to say,
plainly: "REAL, STATED LIMITATION: this is in-process memory, not a
database... A future multi-process deployment would need a shared
store instead." That was about several uvicorn workers.

A later commit added write-through to disk, which made the queue
survive a RESTART, and left the limitation text describing a problem
that now looked solved. It was not: memory was still the truth, the
file was read only at startup, and a SECOND PROCESS -- a sync started
by cron, whose trigger proposes a write -- would write to a file the
running API never read again.

Every SQLite-backed queue worth copying puts it the other way round:
"the database is still the source of truth". That is what this is now.

WHAT THAT DISSOLVES. Merging another process's rows into memory would
have needed a tombstone set, because a decided write whose row failed
to delete would come back. With no second copy, there is nothing to
disagree with.

RESERVING IS A DATABASE-BACKED CLAIM:
`UPDATE ... SET reserved = 1 WHERE write_id = ? AND reserved = 0`,
which either takes the row or matches nothing -- across threads and
processes, because SQLite serialises writers.

EXPIRY IS LAZY, checked at the top of each call rather than on a
timer, and each expiry is audit-logged. `DELETE ... RETURNING` means
exactly one caller -- in one process -- deletes and logs a given write,
so two processes sweeping at once cannot log it twice.

Uniform denial on purpose: an unknown id, an expired one and one the
caller may not act on all answer the same way, as everywhere else in
this project (see core/ontology/mediator.py).

Used by: api/app.py (one instance, on app.state), api/routes.py, and
scripts/run_sync.py (a separate process, which is the reason for all
of the above).
"""

import logging
import tempfile
import threading
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.intermediate_layer.audit import AuditLog
from core.ontology.write_mediator import PendingWrite
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_serialisation import (
    UnreadablePendingWrite,
    from_row,
    to_row,
)

DEFAULT_TTL = timedelta(minutes=15)

logger = logging.getLogger(__name__)


def _stamp(moment: datetime) -> str:
    """A timestamp that sorts correctly AS TEXT.

    EXPIRY IS A STRING COMPARISON IN SQL, so the format decides whether
    it is right. Fixed microsecond width and a single offset make
    lexical order match time order. Rows written by the earlier
    write-through version used plain isoformat(), which omits
    microseconds when they are zero -- and those still compare
    correctly, because "+" sorts before ".", so a whole second sorts
    before any fraction of it. A test pins that.
    """
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class TaskApproval:
    """One reviewer's decision about one task.

    A TASK IS ONE SUB-WRITE, which is Foundry's own unit: "a task is an
    individual change". A bulk action naming fifty objects is fifty
    tasks, and a reviewer may be eligible for some and not others.

    IDENTIFIED BY POSITION, not by object. A create has no object_id
    yet, and nothing forbids two sub-writes touching one object, so
    (type, id) is not a key. The sub_writes tuple is fixed when the
    write is proposed, so an index cannot collide or drift.
    """

    approver_user_id: str
    approved: bool
    decided_at: datetime


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
    """Writes awaiting a decision, held in the database."""

    def __init__(self, ttl: timedelta = DEFAULT_TTL,
                 audit_log: AuditLog | Callable[[], AuditLog] | None = None,
                 persistence: PendingWritePersistence | None = None,
                 clock: Callable[[], datetime] | None = None):
        """`audit_log` may be an instance or a callable returning one.

        A CALLABLE because this store outlives a configuration reload
        while the audit log does not: each generation builds its own,
        stamped with its own generation number. Holding an instance
        would record an expiry after a reload against the log from
        STARTUP -- a wrong-but-plausible value in an audit trail, which
        is worse than an obviously missing one.

        `persistence` SAYS WHERE THE DATABASE IS. Absent, the store
        makes a private one in a temporary directory -- so a store
        built without thought still behaves exactly like the real one
        rather than falling back to a different code path. There is
        only one implementation now, and that is the point.

        `clock` EXISTS FOR TESTS, which need to age a write without
        waiting fifteen minutes. Two tests used to reach into the
        private dict and rewrite `expires_at`; with no dict, a clock is
        the honest seam.
        """
        self._ttl = ttl
        self._audit_log = audit_log if audit_log is not None else AuditLog()
        self._persistence = persistence or PendingWritePersistence(
            Path(tempfile.mkdtemp(prefix="elysium-pending-")) / "pending.db",
        )
        self._clock = clock or (lambda: datetime.now(UTC))
        # IN-PROCESS ONLY, and not what makes this safe. Atomicity comes
        # from SQL; this keeps one process's threads from interleaving
        # a read-then-write they would otherwise both have to retry.
        self._lock = threading.Lock()

    @property
    def audit_log(self) -> AuditLog:
        return self._audit_log() if callable(self._audit_log) else self._audit_log

    def _connection(self):
        return self._persistence.connection()

    def _expire_stale(self, conn) -> None:
        """Deletes and audit-logs every write past its TTL.

        `DELETE ... RETURNING`, so each expired write is removed and
        logged by exactly ONE caller. Two processes sweeping at once
        each get the rows they deleted and none of the other's --
        without it, both would select the same rows and log them twice.
        """
        expired = conn.execute(
            "DELETE FROM pending_writes WHERE expires_at <= ? "
            "RETURNING write_id, owner_user_id, payload",
            (_stamp(self._clock()),),
        ).fetchall()
        for row in expired:
            conn.execute(
                "DELETE FROM pending_write_decisions WHERE write_id = ?",
                (row["write_id"],),
            )
        conn.commit()
        for row in expired:
            try:
                description = from_row(row["payload"]).description
            except UnreadablePendingWrite:
                description = "(unreadable)"
            self.audit_log.log_write_expired(
                row["write_id"], row["owner_user_id"], description,
            )

    def _load(self, conn, write_id: str) -> tuple[PendingWrite, bool] | None:
        """One write and whether it is reserved, or None.

        UNREADABLE MEANS ABSENT. A row this build cannot parse is one
        nobody here can act on, and reporting it as present would offer
        a decision that fails the moment somebody takes it.
        """
        row = conn.execute(
            "SELECT payload, reserved FROM pending_writes WHERE write_id = ?",
            (write_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            return from_row(row["payload"]), bool(row["reserved"])
        except UnreadablePendingWrite as e:
            logger.warning("pending write %s is unreadable: %s", write_id, e)
            return None

    def store(self, pending: PendingWrite) -> str:
        """Queues one write. RAISES if it cannot be stored.

        NOT BEST-EFFORT ANY MORE. When memory was the truth, a write
        that could not reach disk still existed. Now there is no other
        copy: a write that cannot be stored does not exist, and the
        caller must hear so rather than be told it was queued.
        """
        write_id = str(uuid.uuid4())
        with self._lock, self._connection() as conn:
            self._expire_stale(conn)
            conn.execute(
                "INSERT INTO pending_writes (write_id, owner_user_id, "
                "expires_at, payload, reserved) VALUES (?, ?, ?, ?, 0)",
                (write_id, pending.user_id,
                 _stamp(self._clock() + self._ttl), to_row(pending)),
            )
            conn.commit()
        return write_id

    def record_task_decision(self, write_id: str, task_index: int,
                             approver_user_id: str, approved: bool) -> bool:
        """Records one reviewer's decision on one task.

        FALSE FOR A WRITE THAT IS GONE, rather than raising. A write can
        expire between a reviewer opening their inbox and deciding, and
        that is an ordinary race rather than an error.

        A REJECTION IS RECORDED, NOT ACTED ON. It blocks invocation
        because the request is not fully approved -- the same mechanism
        as a task nobody has looked at yet.

        WHAT THAT RECORD IS AND IS NOT, corrected. This used to say it
        "keeps the record of who said no". It does not: these rows are
        deleted with the write, both on expiry and when `reserved()`
        consumes it. The decisions table is the STATE OF AN OPEN
        REQUEST, not the history of one. The durable record of who said
        no is the audit log.

        A REJECTION IS NOT OVERWRITTEN BY SOMEBODY ELSE'S APPROVAL.
        `INSERT OR REPLACE` is keyed on (write_id, task_index), so a
        second reviewer approving a task a first had rejected replaced
        the row and the refusal vanished -- reviewer-shopping, with no
        trace that anyone objected. Measured:

            A rejects  -> fully_approved=False, record: approver_a
            B approves -> fully_approved=True,  record: approver_b

        NOT REACHABLE THROUGH THE API TODAY, and that is said plainly
        rather than dressed up: the route consumes the write on any
        rejection, so no rejected write survives for a second reviewer
        to find. This closes it at the store, because the store is what
        a future partial-rejection feature would call -- Foundry scopes
        a decision to "all tasks in the request that you are eligible
        to review", which is exactly the shape that would leave a
        rejected task sitting beside undecided ones.

        THE SAME REVIEWER MAY STILL CHANGE THEIR MIND. What is refused
        is one person overturning another's refusal, which is the
        four-eyes property; a reviewer correcting their own click is
        not.
        """
        with self._lock, self._connection() as conn:
            self._expire_stale(conn)
            loaded = self._load(conn, write_id)
            if loaded is None:
                return False
            pending, _ = loaded
            if not 0 <= task_index < len(pending.sub_writes):
                raise IndexError(
                    f"write {write_id} has {len(pending.sub_writes)} task(s); "
                    f"no task {task_index}"
                )
            existing = self._decisions(conn, write_id).get(task_index)
            if (
                existing is not None
                and not existing.approved
                and approved
                and existing.approver_user_id != approver_user_id
            ):
                raise PermissionError(
                    f"task {task_index} of write {write_id} was rejected by "
                    f"{existing.approver_user_id!r}; another reviewer cannot approve "
                    f"over that refusal"
                )
            conn.execute(
                "INSERT OR REPLACE INTO pending_write_decisions "
                "(write_id, task_index, approver_user_id, approved, decided_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (write_id, task_index, approver_user_id,
                 1 if approved else 0, _stamp(self._clock())),
            )
            conn.commit()
            return True

    def task_decisions(self, write_id: str) -> dict[int, TaskApproval]:
        """Who has decided which task, keyed by index. Empty if gone.

        A COPY, by construction now: every call reads the database, so
        nothing returned can mutate the store.
        """
        with self._lock, self._connection() as conn:
            self._expire_stale(conn)
            if self._load(conn, write_id) is None:
                return {}
            return self._decisions(conn, write_id)

    @staticmethod
    def _decisions(conn, write_id: str) -> dict[int, TaskApproval]:
        rows = conn.execute(
            "SELECT task_index, approver_user_id, approved, decided_at "
            "FROM pending_write_decisions WHERE write_id = ?",
            (write_id,),
        ).fetchall()
        return {
            row["task_index"]: TaskApproval(
                approver_user_id=row["approver_user_id"],
                approved=bool(row["approved"]),
                decided_at=datetime.fromisoformat(row["decided_at"]),
            )
            for row in rows
        }

    def is_fully_approved(self, write_id: str) -> bool:
        """Every task approved. Absent means undecided, not rejected.

        "Every task must be approved for the request to be invoked" --
        one undecided task keeps the whole write waiting.
        """
        with self._lock, self._connection() as conn:
            self._expire_stale(conn)
            loaded = self._load(conn, write_id)
            if loaded is None:
                return False
            pending, _ = loaded
            decisions = self._decisions(conn, write_id)
            return all(
                index in decisions and decisions[index].approved
                for index in range(len(pending.sub_writes))
            )

    def awaiting(self, may_claim) -> list[tuple[str, PendingWrite]]:
        """Every unreserved write this caller may decide on.

        THE SAME PREDICATE AS THE CLAIM. An inbox that decided
        eligibility differently would show writes that cannot be
        claimed, or hide ones that can -- and the second is worse,
        because an approver would never learn a decision was theirs.

        READ FROM THE DATABASE ON EVERY CALL, which is the whole fix: a
        write another process proposed a moment ago is in this list.

        ONE UNREADABLE ROW COSTS ITS OWN WRITE, not the inbox.
        """
        with self._lock, self._connection() as conn:
            self._expire_stale(conn)
            rows = conn.execute(
                "SELECT write_id, payload FROM pending_writes "
                "WHERE reserved = 0 ORDER BY expires_at",
            ).fetchall()
        found = []
        for row in rows:
            try:
                pending = from_row(row["payload"])
            except UnreadablePendingWrite as e:
                logger.warning(
                    "pending write %s is unreadable: %s", row["write_id"], e,
                )
                continue
            if may_claim(pending):
                found.append((row["write_id"], pending))
        return found

    def expires_at(self, write_id: str) -> str | None:
        """When a write stops being decidable, as an ISO timestamp.

        SEPARATE FROM awaiting(), because expiry is the store's own
        bookkeeping rather than part of the write.
        """
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT expires_at FROM pending_writes WHERE write_id = ?",
                (write_id,),
            ).fetchone()
        return row["expires_at"] if row is not None else None

    @contextmanager
    def reserved(self, write_id: str, may_claim):
        """Holds a write while a decision is made, then commits or releases.

        WHY TWO PHASES. A one-step claim removed the write and handed it
        back, and the decision could then FAIL -- a four-eyes rule
        refusing a self-approval, a field the ontology no longer
        declares. The proposal was already gone. Every control built
        for this flow landed AFTER the point of no return.

        THE CLAIM IS ONE SQL STATEMENT, and that is what makes it safe
        across processes: `UPDATE ... WHERE reserved = 0` either takes
        the row or matches nothing because somebody else did. The
        predicate is checked first; a row that changes hands between
        the check and the claim simply fails to claim.

        A CONTEXT MANAGER, because the release is the half that gets
        forgotten. Any exception in the body puts the write back; only
        a clean exit consumes it.

        A CRASH BETWEEN RESERVE AND COMMIT leaves a write reserved,
        which is why expiry still removes reserved writes: the TTL is
        the backstop, and a stuck reservation resolves itself.
        """
        with self._lock, self._connection() as conn:
            self._expire_stale(conn)
            loaded = self._load(conn, write_id)
            pending = None
            if loaded is not None and not loaded[1] and may_claim(loaded[0]):
                claimed = conn.execute(
                    "UPDATE pending_writes SET reserved = 1 "
                    "WHERE write_id = ? AND reserved = 0",
                    (write_id,),
                ).rowcount
                conn.commit()
                if claimed:
                    pending = loaded[0]

        if pending is None:
            yield None
            return

        committed = False
        try:
            yield pending
            committed = True
        finally:
            with self._lock, self._connection() as conn:
                if committed:
                    conn.execute(
                        "DELETE FROM pending_write_decisions WHERE write_id = ?",
                        (write_id,),
                    )
                    conn.execute(
                        "DELETE FROM pending_writes WHERE write_id = ?",
                        (write_id,),
                    )
                else:
                    conn.execute(
                        "UPDATE pending_writes SET reserved = 0 "
                        "WHERE write_id = ?",
                        (write_id,),
                    )
                conn.commit()

    def duplicates_of(self, write_id: str) -> int:
        """How many OTHER pending writes propose the same change.

        SURFACED, NOT PREVENTED. A second identical proposal might be a
        double-click, a colleague re-requesting something forgotten, or
        a deliberate nudge; Elysium cannot tell which, and Foundry
        allows duplicates too and relies on the reviewer seeing them
        together.

        IDENTITY IS THE CHANGE, NOT THE PROPOSER. Two people
        independently proposing the same edit is the clearest duplicate
        there is. Reserved writes are counted, so the number does not
        flicker while somebody decides on one.
        """
        with self._lock, self._connection() as conn:
            self._expire_stale(conn)
            loaded = self._load(conn, write_id)
            if loaded is None:
                return 0
            rows = conn.execute(
                "SELECT payload FROM pending_writes WHERE write_id != ?",
                (write_id,),
            ).fetchall()
        fingerprint = _fingerprint(loaded[0])
        count = 0
        for row in rows:
            try:
                if _fingerprint(from_row(row["payload"])) == fingerprint:
                    count += 1
            except UnreadablePendingWrite:
                continue
        return count

    def claim(self, write_id: str, may_claim) -> PendingWrite | None:
        """Removes and returns a write, if the caller may act on it.

        ONE STEP: reserve and commit at once. Kept for callers that
        decide nothing that can fail afterwards -- `reserved` is the
        form to use when a decision can.

        NOW RESPECTS RESERVATION, which the in-memory version did not:
        it could remove a write out from under somebody mid-decision.
        Going through `reserved` makes that impossible, because the
        claim is the same single UPDATE.
        """
        with self.reserved(write_id, may_claim) as pending:
            return pending
