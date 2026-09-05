"""
session_store.py  (create/validate/invalidate login sessions)

Tokens via secrets.token_urlsafe() -- cryptographically secure,
unpredictable, never anything hand-rolled (e.g. never a UUID derived
from predictable state, never a counter). SESSION_LIFETIME is a fixed
absolute expiry from creation -- a real, mandatory TTL, not an
unbounded session; a future refinement could add idle-timeout on top,
but an absolute cap exists from the start rather than being deferred
indefinitely.

validate_session() NEVER distinguishes "token doesn't exist" from
"token expired" -- both return None, same uniform-denial principle
used everywhere else in this project (a caller learns nothing about
WHY a token failed, only that it did; the real reason is only ever
visible in the audit log via whatever calls this).

invalidate_all_sessions() covers TWO real scenarios with the same
method: a user revoking their own other sessions (a lost device), and
an admin forcibly revoking someone's access (suspected compromise, or
as part of disabling/deleting an account -- see core/user_directory.py).
Deliberately revokes EVERY session for that username, including
whichever one made the current request -- simpler and more
conservative than trying to carve out "all except this one," and
matches the same "if in doubt, everyone re-authenticates" discipline
used throughout this project's security design.

Used by: api/'s auth dependency, resolving a request's token into a
         real user_id before anything downstream (AgentLoop,
         WriteMediator, DataMediator) is ever touched; api/routes.py
         for login/logout/logout-all/admin-revoke.
"""

import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.auth.database import connection

SESSION_LIFETIME = timedelta(hours=24)


class SessionStore:
    """Creates, validates and invalidates login sessions.

    ONE class, not a Reader/Writer pair. This store was briefly split
    into two during the read-only mirror work, then deliberately
    reverted: the split was pattern-matching, not a real requirement.
    The genuine guarantee that work provides is that Elysium's read
    path cannot write to the CUSTOMER'S OWN external database --
    someone else's production system, protected from our bugs. This
    table is Elysium's own, written only by Elysium, with no third
    party to protect. Splitting it made callers pick a half for a
    failure mode that was never real.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def validate_session(self, token: str) -> str | None:
        with connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT username, expires_at FROM sessions WHERE token = ?", (token,)
            ).fetchone()

        if row is None:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(UTC) >= expires_at:
            return None

        return row["username"]

    def create_session(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = now + SESSION_LIFETIME
        with connection(self._db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (token, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, username, now.isoformat(), expires_at.isoformat()),
            )
            conn.commit()
        return token

    def invalidate_session(self, token: str) -> None:
        with connection(self._db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()

    def invalidate_all_sessions(self, username: str) -> None:
        with connection(self._db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
            conn.commit()
