"""
login_attempt_tracker.py  (rate-limit repeated failed logins, per
username)

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

Used by: api/routes.py's own login() route, the only caller.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.auth.database import connection
from core.sqlite_connection import immediate_transaction

MAX_ATTEMPTS = 5
WINDOW = timedelta(minutes=15)


class LoginAttemptTracker:
    """Rate-limits repeated failed logins, per username.

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

    def is_locked_out(self, username: str) -> bool:
        with connection(self._db_path) as conn:
            row = conn.execute(
                "SELECT failed_count, window_started_at FROM login_attempts WHERE username = ?", (username,)
            ).fetchone()

        if row is None:
            return False

        window_started_at = datetime.fromisoformat(row["window_started_at"])
        if datetime.now(UTC) - window_started_at >= WINDOW:
            # The window itself has expired -- a stale record, not a
            # real, current lockout. Left in place rather than deleted
            # here, because a read-only METHOD deleting rows would be a
            # real, surprising side effect; record_failure() below is
            # what actually resets it, the next time this username is
            # used at all.
            #
            # THE CONNECTION IS NOT READ-ONLY, whatever this comment
            # used to say (001's F-12b). It claimed "a STRUCTURALLY
            # read-only connection besides -- it couldn't delete even
            # if it tried", and that was false: connection() reaches
            # open_connection() with read_only defaulting to False,
            # which it must, because connection_with_schema() runs
            # CREATE TABLE IF NOT EXISTS and column migrations through
            # the same handle. PROVED by writing AND deleting a row
            # through this very helper before correcting this.
            #
            # So the discipline here is a CONVENTION, not a guarantee,
            # and saying otherwise is worse than saying nothing: a
            # false structural claim in an auth file invites the next
            # reader to skip a check they would otherwise make. See
            # tests/unit/test_auth_connection_is_writable.py, which
            # pins the truth so the claim cannot be re-made quietly.
            return False

        return row["failed_count"] >= MAX_ATTEMPTS

    def record_failure(self, username: str) -> None:
        # An immediate transaction: this counter is read, compared
        # against its window, then written. Without it two concurrent
        # calls can both read the same count and both write count+1 as
        # the same value -- silently undercounting, which for a rate
        # limiter means letting through more than the configured limit.
        with connection(self._db_path) as conn, immediate_transaction(conn):
            row = conn.execute(
                "SELECT failed_count, window_started_at FROM login_attempts WHERE username = ?", (username,)
            ).fetchone()

            now = datetime.now(UTC)
            # EXPIRED ROWS GO, as each failure is recorded (E-02). They
            # were never deleted, so every username ever tried stayed for
            # good -- a table anyone could grow without logging in. An
            # expired row changes no decision (is_locked_out treats a
            # window past WINDOW as over), so deleting it changes none.
            # Text comparison orders them: every timestamp here is written
            # by the same isoformat(), in UTC.
            conn.execute(
                "DELETE FROM login_attempts WHERE window_started_at <= ?",
                ((now - WINDOW).isoformat(),),
            )
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

    def record_success(self, username: str) -> None:
        # Clears any prior failures -- a real, successful login means
        # whoever just authenticated genuinely knows the password now,
        # regardless of how many earlier attempts (their own typos, or
        # someone else's) came before it.
        with connection(self._db_path) as conn:
            conn.execute("DELETE FROM login_attempts WHERE username = ?", (username,))
            conn.commit()
