"""
login_attempt_tracker.py  (rate-limit repeated failed logins, per
username)

Two real, separate classes -- LoginAttemptReader(InternalReadAdapter)
and LoginAttemptWriter(InternalWriteAdapter) -- not one, combined
class, matching the same real pattern already proved for
QueryRateLimiter, CredentialStore, and SessionStore (see core/
internal_storage.py's own module docstring for the fuller design
reasoning -- CQRS, Python's own typeshed precedent -- settled before
any of these four splits was written).

A real, found gap this project shipped without: nothing throttled
/login at all -- an attacker could script unlimited password guesses
against any username with no backend-enforced slowdown. Closed here.

Keyed by the RAW, SUBMITTED username string -- NOT verified to be a
real account first. This is deliberate, not an oversight: it's what
makes a nonexistent username behave IDENTICALLY to a real one under
repeated failure (both eventually lock out the same way), preserving
this project's own, already-established "never let a caller
distinguish an existing account from a nonexistent one" principle
(see credential_store.py's own verify_credential() and api/routes.py's
own login() route). Rate-limiting only REAL usernames would itself be
a new side channel: an attacker could tell a username is real simply
by noticing it starts getting throttled and a made-up one never does.

MAX_ATTEMPTS/WINDOW chosen as a reasonable, common industry default
(5 failures / 15 minutes), not tuned against this specific
deployment's own traffic -- revisit if real, observed abuse patterns
ever call for something stricter or looser.

A locked-out account's login is STILL a genuine 401 with the SAME
generic "Invalid username or password" message every other failure
mode already uses -- never a distinct status/message. A different
response for "locked out" vs "just wrong" would itself leak that this
account has real, recent activity against it. The one place this
distinction genuinely needs to exist is server-side, for anyone
investigating later -- see the real reason logged wherever this is
called from (api/routes.py's own login() route), the same "uniform
denial to the caller, real reason in the audit trail" pattern
core/auth/session_store.py's own validate_session() already follows.

TIMING SAFETY: is_locked_out() is checked BEFORE the real password
verification, but api/routes.py's own login() route deliberately
still runs verify_credential() UNCONDITIONALLY regardless of the
lockout result -- a locked-out account short-circuiting BEFORE that
real, expensive argon2id check would itself create a NEW timing side
channel this project had already, carefully avoided for the disabled-
account case (see that route's own comment): a locked-out response
would return measurably faster than a real wrong-password check,
leaking "this account exists and has recent failed attempts against
it" through response timing alone. Never move that ordering without
re-reading this.

LoginAttemptWriter's own two methods deliberately do NOT use
InternalWriteAdapter's own, simpler _connection() -- the same real,
considered choice already made for every prior split's own writer, for
the identical reason: the login_attempts table's own schema needs to
genuinely exist first; core/auth/database.py's own schema-aware
connection() already, correctly guarantees that. LoginAttemptReader's
own is_locked_out(), by contrast, DOES use InternalReadAdapter's own,
real, structurally read-only _connection() directly.

Used by: api/routes.py's own login() route, the only caller.
"""

from datetime import UTC, datetime, timedelta

from core.auth.database import connection
from core.internal_storage import InternalReadAdapter, InternalWriteAdapter

MAX_ATTEMPTS = 5
WINDOW = timedelta(minutes=15)


class LoginAttemptReader(InternalReadAdapter):
    def is_locked_out(self, username: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT failed_count, window_started_at FROM login_attempts WHERE username = ?", (username,)
            ).fetchone()

        if row is None:
            return False

        window_started_at = datetime.fromisoformat(row["window_started_at"])
        if datetime.now(UTC) - window_started_at >= WINDOW:
            # The window itself has expired -- a stale record, not a
            # real, current lockout. Left in place rather than deleted
            # here (a read-only method deleting rows would be a real,
            # surprising side effect, and this is now a STRUCTURALLY
            # read-only connection besides -- it couldn't delete even
            # if it tried); record_failure() below is what actually
            # resets it, the next time this username is used at all.
            return False

        return row["failed_count"] >= MAX_ATTEMPTS


class LoginAttemptWriter(InternalWriteAdapter):
    def record_failure(self, username: str) -> None:
        with connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT failed_count, window_started_at FROM login_attempts WHERE username = ?", (username,)
            ).fetchone()

            now = datetime.now(UTC)
            if row is None or now - datetime.fromisoformat(row["window_started_at"]) >= WINDOW:
                # No record yet, or the previous window has fully
                # expired -- start a genuinely fresh one, not an
                # ever-growing count from a much earlier, unrelated
                # burst of attempts.
                conn.execute(
                    """
                    INSERT INTO login_attempts (username, failed_count, window_started_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(username) DO UPDATE SET failed_count = 1, window_started_at = excluded.window_started_at
                    """,
                    (username, now.isoformat()),
                )
            else:
                conn.execute(
                    "UPDATE login_attempts SET failed_count = failed_count + 1 WHERE username = ?", (username,)
                )
            conn.commit()

    def record_success(self, username: str) -> None:
        # Clears any prior failures -- a real, successful login means
        # whoever just authenticated genuinely knows the password now,
        # regardless of how many earlier attempts (their own typos, or
        # someone else's) came before it.
        with connection(self.db_path) as conn:
            conn.execute("DELETE FROM login_attempts WHERE username = ?", (username,))
            conn.commit()
