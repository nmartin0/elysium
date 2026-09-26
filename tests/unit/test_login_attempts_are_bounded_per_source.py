"""One source cannot fill the login_attempts table (E-02's residual).

WHAT WAS LEFT OPEN. Patch 321 bounded the LENGTH of a username and a
presented password, which killed the reported attack -- ten requests
took credentials.db from 100 KB to 16.3 MB. It did not bound the
NUMBER of distinct usernames one window can hold. Measured afterwards:
400 unauthenticated requests with legal-length usernames wrote 400
rows and 122,880 bytes, ~307 bytes each, extrapolating to ~28 MB at
100 req/s and ~276 MB at 1,000, over one window, with no account.

OWASP names the category: "this problem is exacerbated if session data
is also tracked prior to a login, as a user can launch the attack
without the need of an account."

WHY NOT A GLOBAL CAP, which was proposed and then withdrawn. It is
unsafe in BOTH eviction directions:

    evict old rows    an attacker floods junk usernames, a victim's
                      failed-attempt row is evicted with them, their
                      count resets, and the lockout protecting them
                      is gone
    refuse new rows   an attacker fills the table and NO new username
                      gets lockout protection at all

Both are complete bypasses of the control. A per-source budget cannot
be spent by anyone but its own source.

WHY NOT "ONLY TRACK REAL USERNAMES", which would bound it neatly:
"because you cannot lock out an account that does not exist, only
valid account names will lock" -- which tells an attacker which
usernames are real. Keying by the RAW username is deliberate.

WHAT IT COSTS, and the test for it is below rather than only the
prose: a source that exhausts its budget stops STARTING to track new
usernames. Rows it already has keep counting. A genuinely new user
behind the same address -- a large NAT with an attacker behind it --
does not get a lockout row until the window rolls.
"""

import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.auth.login_attempt_tracker import (
    MAX_ATTEMPTS,
    WINDOW,
    LoginAttemptTracker,
)
from core.auth.login_attempt_tracker import MAX_NEW_USERNAMES_PER_SOURCE as BUDGET

ATTACKER = "203.0.113.9"
ELSEWHERE = "198.51.100.4"


@pytest.fixture
def tracker():
    return LoginAttemptTracker(Path(tempfile.mkdtemp()) / "credentials.db")


def _rows(tracker) -> int:
    with sqlite3.connect(tracker._db_path) as conn:
        return conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0]


def _count_for(tracker, username: str) -> int:
    with sqlite3.connect(tracker._db_path) as conn:
        row = conn.execute(
            "SELECT failed_count FROM login_attempts WHERE username = ?", (username,)
        ).fetchone()
    return 0 if row is None else row[0]


class TestTheBudgetHolds:
    def test_one_source_cannot_write_more_than_its_budget(self, tracker):
        for index in range(BUDGET * 8):
            tracker.record_failure(f"victim{index:04d}", source=ATTACKER)

        assert _rows(tracker) == BUDGET

    def test_another_source_is_unaffected(self, tracker):
        """THE WHOLE POINT OF PER-SOURCE. A global cap would have let
        the flood above deny this."""
        for index in range(BUDGET * 2):
            tracker.record_failure(f"victim{index:04d}", source=ATTACKER)

        tracker.record_failure("real_user", source=ELSEWHERE)

        assert _count_for(tracker, "real_user") == 1

    def test_a_user_already_tracked_keeps_counting(self, tracker):
        """An exhausted source stops STARTING new rows. Anyone already
        being tracked stays protected -- otherwise exhausting the
        budget would switch lockout off for the very accounts under
        attack."""
        for index in range(BUDGET * 2):
            tracker.record_failure(f"victim{index:04d}", source=ATTACKER)

        tracker.record_failure("victim0000", source=ATTACKER)

        assert _count_for(tracker, "victim0000") == 2

    def test_lockout_still_reached_for_a_tracked_user(self, tracker):
        """The control this protects still works end to end."""
        for _ in range(MAX_ATTEMPTS):
            tracker.record_failure("target", source=ATTACKER)

        assert tracker.is_locked_out("target") is True

    def test_the_budget_refreshes_when_the_window_rolls(self, tracker):
        """A source that behaved an hour ago is not charged for it."""
        for index in range(BUDGET):
            tracker.record_failure(f"old{index:04d}", source=ATTACKER)
        stale = (datetime.now(UTC) - WINDOW - timedelta(minutes=1)).isoformat()
        with sqlite3.connect(tracker._db_path) as conn:
            conn.execute("UPDATE login_attempts SET window_started_at = ?", (stale,))
            conn.commit()

        tracker.record_failure("newcomer", source=ATTACKER)

        assert _count_for(tracker, "newcomer") == 1


class TestWhatMustNotChange:
    def test_no_source_means_todays_behaviour_exactly(self, tracker):
        """No caller passes a source yet -- api/routes.py is backend's
        file. Until it does, nothing may change."""
        for index in range(BUDGET * 3):
            tracker.record_failure(f"u{index}")

        assert _rows(tracker) == BUDGET * 3

    def test_a_row_with_no_source_is_charged_to_nobody(self, tracker):
        """Rows written before the `source` column existed carry NULL.
        Counting them against a budget would make a deployment that
        upgraded mid-window refuse real users."""
        for index in range(BUDGET):
            tracker.record_failure(f"legacy{index:04d}")

        tracker.record_failure("newcomer", source=ATTACKER)

        assert _count_for(tracker, "newcomer") == 1

    def test_a_success_still_clears_the_failures(self, tracker):
        tracker.record_failure("alice", source=ELSEWHERE)
        tracker.record_success("alice")

        assert _count_for(tracker, "alice") == 0

    def test_expired_rows_are_still_deleted(self, tracker):
        """E-02's other half, from patch 321, must survive this."""
        old = (datetime.now(UTC) - WINDOW - timedelta(minutes=1)).isoformat()
        # Touch the tracker first: the schema is created on the first
        # connection through core.auth.database, so a raw sqlite3
        # INSERT before that finds no table. Found by the test failing.
        tracker.is_locked_out("nobody")
        with sqlite3.connect(tracker._db_path) as conn:
            conn.execute("INSERT INTO login_attempts (username, failed_count, window_started_at) "
                         "VALUES ('long_gone', 3, ?)", (old,))
            conn.commit()

        tracker.record_failure("someone", source=ELSEWHERE)

        with sqlite3.connect(tracker._db_path) as conn:
            names = {row[0] for row in conn.execute("SELECT username FROM login_attempts")}
        assert "long_gone" not in names


class TestTheOperatorIsTold:
    def test_an_exhausted_source_is_logged_once_not_once_per_attempt(self, tracker, caplog):
        """FOUND BY RUNNING IT. The first version logged inside the
        refusal, so a 400-request enumeration produced 350 identical
        warnings -- log flooding, which is a smaller version of the
        storage flooding this change exists to stop."""
        with caplog.at_level("WARNING"):
            for index in range(BUDGET * 8):
                tracker.record_failure(f"victim{index:04d}", source=ATTACKER)

        warnings = [r for r in caplog.records if "has started tracking" in r.getMessage()]
        assert len(warnings) == 1, f"{len(warnings)} warnings for one source"
        assert ATTACKER in warnings[0].getMessage()

    def test_a_source_that_stays_inside_its_budget_is_not_logged(self, tracker, caplog):
        """THE OPPOSITE DIRECTION. A warning on every source would be
        noise, and noise is how the real one gets missed."""
        with caplog.at_level("WARNING"):
            for index in range(BUDGET - 1):
                tracker.record_failure(f"ordinary{index:04d}", source=ELSEWHERE)

        assert not [r for r in caplog.records if "has started tracking" in r.getMessage()]
