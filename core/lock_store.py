"""
lock_store.py  (generic, resource-agnostic pessimistic locking with
lease-based auto-expiry)

Built as part of the app shell, NOT config-builder-specific -- see
the design spec's own Section 1.6. The config builder is the first,
concrete consumer (its own draft-editing lock), but this class knows
nothing about config drafts, or any other specific resource -- it is
keyed purely by an arbitrary `resource_name` string, so any future
sub-app needing "one editor at a time" semantics can reuse it as-is.

THE PATTERN, matching a real, established one (pessimistic locking
with a lease/timeout, confirmed against a real framework's own docs,
e.g. Jmix's own @PessimisticLock) -- not a bespoke design:
  - Pessimistic: acquiring a lock on a resource someone else already
    holds fails outright, rather than optimistically allowing both
    edits through and reconciling conflicts after the fact.
  - Lease-based: every lock has a real, fixed expiry (LEASE_DURATION
    from the moment of acquire/refresh) -- a crashed or abandoned
    editing session can never lock a resource forever. The current
    holder can REFRESH their own lease indefinitely while still
    actively working (see refresh()); anyone else must wait for
    either an explicit release() or the lease to actually expire.
  - Fencing: validate() is the one method a caller MUST use again,
    right before the real, underlying write/publish actually happens
    -- not just once, back when editing started. A token that was
    valid when acquired can still have since expired (or been force-
    released, or superseded by the same user re-acquiring from a
    different tab, see acquire()'s own docstring) by the time the
    real write is attempted; validate() is what catches a stale
    session trying to write anyway over someone else's newer work.
  - Manual override: force_release() is the "Locks Admin UI"
    capability real systems (Jmix again) ship -- deletes the lock
    unconditionally, no token or ownership check. This class itself
    knows nothing about permissions at all (same discipline as
    SessionStore, PendingWriteStore, every other store in this
    project) -- the CALLER (an HTTP route) is responsible for
    checking the caller holds whatever permission gates force-release
    for this specific resource before ever calling this method. See
    api/routes.py's own force-release route for the real, current
    example (gated by manage:locks).

A CLASS, not free functions taking db_path on every call -- same
reasoning as core/auth/session_store.py's own SessionStore (see its
docstring): db_path is genuinely this store's own persistent state.
One instance, constructed once at app-startup, shared by every
caller -- see api/app.py.

Its own, dedicated SQLite file (deployment/var/lib/resource_locks.db)
-- matches the existing write_log.db precedent (core/ontology/
write_log.py's own module docstring: "a new concern gets its own
file, not folded into an unrelated one"), and the name is
deliberately generic, not config_lock.db -- this class has no
config-builder-specific knowledge at all, and naming its own storage
file after one specific, current consumer would misstate that.

Used by: api/routes.py's generic /locks/{resource_name}/* routes,
         built as this class's own "minimal way to exercise it" (see
         the design spec's own Build Order) -- genuinely reusable
         endpoints, not a throwaway test harness, since the config
         builder (once built) can call these exact same routes for
         its own real editing lock.
"""

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core.sqlite_connection import connection_with_schema

LEASE_DURATION = timedelta(minutes=30)


class LockStore:
    """
    Generic, resource-agnostic pessimistic locking with lease-based
    auto-expiry -- see this module's own docstring for the full
    mechanism, history, and scope. One instance per deployment,
    shared by every caller.
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS resource_locks (
        resource_name TEXT PRIMARY KEY,
        token TEXT NOT NULL,
        user_id TEXT NOT NULL,
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    """

    def __init__(self, db_path: Path, lease_duration: timedelta = LEASE_DURATION):
        self._db_path = db_path
        self._lease_duration = lease_duration

    def _connection(self):
        return connection_with_schema(self._db_path, self.SCHEMA)

    def acquire(self, resource_name: str, user_id: str) -> tuple[str, datetime] | None:
        # Returns (token, expires_at) together -- not just the token,
        # with a caller expected to look up the expiry separately
        # afterward. A separate lookup would be BOTH a real, if
        # vanishingly unlikely, correctness gap (the lock could, in
        # principle, have already expired again by the time of that
        # second call, on an extremely short lease) and forces every
        # caller to handle a type that's theoretically None right
        # after they just successfully acquired it -- worse on both
        # counts than simply handing back what this method already,
        # definitely knows at the moment it succeeds.
        #
        # Succeeds (issuing a real, fresh, unpredictable token -- same
        # secrets.token_urlsafe() mechanism as SessionStore's own
        # session tokens, never anything hand-rolled) in every case
        # EXCEPT one: a currently-valid, non-expired lock already held
        # by a DIFFERENT user. This deliberately includes the SAME
        # user calling acquire() again while they already hold a
        # valid lock -- e.g. they lost their own token (a page reload
        # with no client-side persistence, a second browser tab) and
        # need to recover access to the resource they're already
        # editing. Re-acquiring mints a genuinely NEW token, silently
        # superseding whichever old one existed -- any OTHER tab still
        # holding the stale token becomes correctly fenced out the
        # next time it tries to validate() or refresh(), rather than
        # two "valid" tokens for the same resource existing at once.
        now = datetime.now(UTC)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM resource_locks WHERE resource_name = ?", (resource_name,)
            ).fetchone()

            if row is not None:
                expires_at = datetime.fromisoformat(row["expires_at"])
                held_by_someone_else = row["user_id"] != user_id
                if held_by_someone_else and now < expires_at:
                    return None

            token = secrets.token_urlsafe(32)
            new_expires_at = now + self._lease_duration
            conn.execute(
                "INSERT INTO resource_locks (resource_name, token, user_id, acquired_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(resource_name) DO UPDATE SET "
                "token = excluded.token, user_id = excluded.user_id, "
                "acquired_at = excluded.acquired_at, expires_at = excluded.expires_at",
                (resource_name, token, user_id, now.isoformat(), new_expires_at.isoformat()),
            )
            conn.commit()
        return token, new_expires_at

    def refresh(self, resource_name: str, user_id: str, token: str) -> datetime | None:
        # Extends the SAME lock's lease -- the token itself never
        # changes here (unlike acquire()'s own re-acquire path, which
        # deliberately mints a new one). Only succeeds against a
        # lock that is STILL genuinely held by this exact user_id and
        # token, and NOT already expired -- an already-expired lock
        # is, by every other method's own logic, no longer really
        # held at all, so refreshing it would incorrectly resurrect a
        # lease someone else may have already validly acquired in the
        # meantime. The caller's own next move on a None result should
        # be a fresh acquire(), not a retry of refresh().
        now = datetime.now(UTC)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT user_id, token, expires_at FROM resource_locks WHERE resource_name = ?", (resource_name,)
            ).fetchone()
            if row is None or row["user_id"] != user_id or row["token"] != token:
                return None
            if now >= datetime.fromisoformat(row["expires_at"]):
                return None

            new_expires_at = now + self._lease_duration
            conn.execute(
                "UPDATE resource_locks SET expires_at = ? WHERE resource_name = ?",
                (new_expires_at.isoformat(), resource_name),
            )
            conn.commit()
        return new_expires_at

    def release(self, resource_name: str, user_id: str, token: str) -> bool:
        # Matches SessionStore's own invalidate_session(): no expiry
        # check here at all -- releasing your own already-expired
        # lock is a harmless no-op-shaped cleanup, not something worth
        # a separate failure case. Only user_id AND token must match;
        # neither alone is sufficient (a correct user_id with a STALE
        # token -- e.g. a tab superseded by acquire()'s own re-acquire
        # path -- must not be able to release the CURRENT, different
        # session's lock).
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM resource_locks WHERE resource_name = ? AND user_id = ? AND token = ?",
                (resource_name, user_id, token),
            )
            conn.commit()
        return cursor.rowcount > 0

    def force_release(self, resource_name: str) -> bool:
        # Unconditional -- no token or user_id check at all. This is
        # the ONE method in this class with no ownership check
        # whatsoever, by design: see this module's own docstring for
        # why the permission check belongs entirely to the caller, not
        # here.
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM resource_locks WHERE resource_name = ?", (resource_name,))
            conn.commit()
        return cursor.rowcount > 0

    def validate(self, resource_name: str, token: str) -> bool:
        # THE fencing check -- see this module's own docstring. Must
        # be called again, immediately before the real, underlying
        # write/publish happens, not just trusted from whenever the
        # caller originally acquired the lock. Deliberately does NOT
        # distinguish "no lock exists," "token doesn't match," and
        # "lock expired" -- same uniform-denial principle used
        # throughout this project (e.g. SessionStore.validate_session());
        # the caller only needs to know "still valid, or not," not why.
        with self._connection() as conn:
            row = conn.execute(
                "SELECT token, expires_at FROM resource_locks WHERE resource_name = ?", (resource_name,)
            ).fetchone()
        if row is None or row["token"] != token:
            return False
        return datetime.now(UTC) < datetime.fromisoformat(row["expires_at"])

    def get_status(self, resource_name: str) -> dict[str, Any] | None:
        # For a UI to show "currently being edited by X, since Y" --
        # or nothing, if unlocked. An expired row is treated as
        # unlocked here too, same as everywhere else in this class;
        # deliberately does NOT proactively delete the stale row on
        # this read-only path (this table sees, at most, a small
        # handful of real rows ever -- one per distinct resource this
        # whole deployment ever locks -- so an occasional stale row
        # lingering until the next acquire() silently overwrites it
        # costs nothing real, and keeps this method side-effect-free).
        with self._connection() as conn:
            row = conn.execute(
                "SELECT user_id, acquired_at, expires_at FROM resource_locks WHERE resource_name = ?",
                (resource_name,),
            ).fetchone()
        if row is None:
            return None
        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(UTC) >= expires_at:
            return None
        return {
            "resource_name": resource_name,
            "held_by": row["user_id"],
            "acquired_at": row["acquired_at"],
            "expires_at": row["expires_at"],
        }
