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

Every stored write has a real TTL (DEFAULT_TTL) -- an unconfirmed
proposal doesn't linger forever. Expiry is LAZY (checked at the top of
store()/pop(), not a separate periodic background task) -- this is a
low-volume store; noticing an expired entry a little late, at the next
touch rather than on a fixed timer, costs nothing real, and avoids
needing a genuine asyncio background task (which would need a real
startup hook to launch correctly, adding real complexity for no
practical benefit at this volume). Every expiry found this way is
logged via audit.log_write_expired() -- a proposal that's abandoned
still leaves a real trace, not silent disappearance.

pop() is uniform-denial on purpose: wrong user, unknown ID, and
expired ID all return the SAME None -- same principle used everywhere
else in this project (see core/ontology/mediator.py's docstring).

Used by: api/app.py (one instance, stored on app.state, same lifecycle
         as everything else built once at startup), api/routes.py
"""

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core.intermediate_layer.audit import log_write_expired
from core.ontology.write_mediator import PendingWrite

DEFAULT_TTL = timedelta(minutes=15)


@dataclass
class _StoredWrite:
    pending: PendingWrite
    owner_user_id: str
    expires_at: datetime


class PendingWriteStore:
    def __init__(self, ttl: timedelta = DEFAULT_TTL):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._writes: dict[str, _StoredWrite] = {}

    def _expire_stale_locked(self) -> None:
        # Called with self._lock already held.
        now = datetime.now(UTC)
        expired_ids = [write_id for write_id, stored in self._writes.items() if now >= stored.expires_at]
        for write_id in expired_ids:
            stored = self._writes.pop(write_id)
            log_write_expired(write_id, stored.owner_user_id, stored.pending.description)

    def store(self, pending: PendingWrite) -> str:
        write_id = str(uuid.uuid4())
        expires_at = datetime.now(UTC) + self._ttl
        with self._lock:
            self._expire_stale_locked()
            self._writes[write_id] = _StoredWrite(pending, pending.user_id, expires_at)
        return write_id

    def pop(self, write_id: str, requesting_user_id: str) -> PendingWrite | None:
        with self._lock:
            self._expire_stale_locked()
            stored = self._writes.get(write_id)
            if stored is None or stored.owner_user_id != requesting_user_id:
                return None
            del self._writes[write_id]
            return stored.pending
