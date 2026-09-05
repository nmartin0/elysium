"""
session_store.py  (create/validate/invalidate login sessions)

Two real, separate classes -- SessionReader(InternalReadAdapter) and
SessionWriter(InternalWriteAdapter) -- not one, combined class,
matching the same real pattern already established and proved for
QueryRateLimiter and CredentialStore (see core/internal_storage.py's
own module docstring for the fuller design reasoning -- CQRS, Python's
own typeshed precedent -- settled before any of these three splits was
written). Unlike either of those two, BOTH halves here have real,
active, production callers -- validate_session() runs on every single
authenticated request (api/auth_dependency.py's own get_current_user()),
and all three write methods are each a real route's own, direct
mechanism (login, logout, logout-all, and the admin "revoke this
user's sessions" path) -- so both SessionReader and SessionWriter are
genuinely wired into app.state, unlike CredentialWriter's own,
currently-unwired case.

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

SessionWriter's own methods deliberately do NOT use InternalWriteAdapter's
own, simpler _connection() -- the same real, considered choice already
made for QueryRateLimitWriter and CredentialWriter, for the identical
reason: the sessions table's own schema needs to genuinely exist before
any write succeeds, and core/auth/database.py's own schema-aware
connection() (lazy, idempotent CREATE TABLE IF NOT EXISTS) is the real,
already-correct mechanism for that. SessionReader's own
validate_session(), by contrast, DOES use InternalReadAdapter's own
_connection() directly -- a real, structurally read-only guarantee.

Used by: api/'s auth dependency (SessionReader only), resolving a
         request's token into a real user_id before anything
         downstream (AgentLoop, WriteMediator, DataMediator) is ever
         touched; api/routes.py (SessionWriter, for login/logout/
         logout-all/admin-revoke).
"""

import secrets
from datetime import UTC, datetime, timedelta

from core.auth.database import connection
from core.internal_storage import InternalReadAdapter, InternalWriteAdapter

SESSION_LIFETIME = timedelta(hours=24)


class SessionReader(InternalReadAdapter):
    def validate_session(self, token: str) -> str | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT username, expires_at FROM sessions WHERE token = ?", (token,)
            ).fetchone()

        if row is None:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(UTC) >= expires_at:
            return None

        return row["username"]


class SessionWriter(InternalWriteAdapter):
    def create_session(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires_at = now + SESSION_LIFETIME
        with connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO sessions (token, username, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, username, now.isoformat(), expires_at.isoformat()),
            )
            conn.commit()
        return token

    def invalidate_session(self, token: str) -> None:
        with connection(self.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()

    def invalidate_all_sessions(self, username: str) -> None:
        with connection(self.db_path) as conn:
            conn.execute("DELETE FROM sessions WHERE username = ?", (username,))
            conn.commit()
