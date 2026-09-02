"""Tests for core/auth/login_attempt_tracker.py."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.auth.database import connection
from core.auth.login_attempt_tracker import MAX_ATTEMPTS, WINDOW, LoginAttemptTracker


@pytest.fixture
def tracker(tmp_path: Path) -> LoginAttemptTracker:
    return LoginAttemptTracker(tmp_path / "credentials.db")


def test_username_with_no_record_at_all_is_not_locked_out(tracker):
    assert tracker.is_locked_out("alice") is False


def test_not_locked_out_after_fewer_than_max_failures(tracker):
    for _ in range(MAX_ATTEMPTS - 1):
        tracker.record_failure("alice")
    assert tracker.is_locked_out("alice") is False


def test_locked_out_after_exactly_max_failures(tracker):
    for _ in range(MAX_ATTEMPTS):
        tracker.record_failure("alice")
    assert tracker.is_locked_out("alice") is True


def test_locked_out_stays_locked_out_after_further_failures(tracker):
    for _ in range(MAX_ATTEMPTS + 3):
        tracker.record_failure("alice")
    assert tracker.is_locked_out("alice") is True


def test_record_success_clears_a_prior_lockout(tracker):
    for _ in range(MAX_ATTEMPTS):
        tracker.record_failure("alice")
    assert tracker.is_locked_out("alice") is True

    tracker.record_success("alice")

    assert tracker.is_locked_out("alice") is False


def test_record_success_with_no_prior_record_does_not_raise(tracker):
    tracker.record_success("alice")  # does not raise


def test_failures_for_one_username_do_not_affect_another(tracker):
    for _ in range(MAX_ATTEMPTS):
        tracker.record_failure("alice")

    assert tracker.is_locked_out("alice") is True
    assert tracker.is_locked_out("bob") is False


def test_lockout_expires_once_the_window_has_passed(tracker, tmp_path: Path):
    for _ in range(MAX_ATTEMPTS):
        tracker.record_failure("alice")
    assert tracker.is_locked_out("alice") is True

    # Simulates real time passing by directly backdating the row --
    # NOT by patching WINDOW negative DURING the recording loop above
    # (a real mistake caught while writing this test: a negative
    # WINDOW makes record_failure()'s own "has the window expired"
    # check true on EVERY call, so the count never actually reaches
    # MAX_ATTEMPTS in the first place -- it keeps resetting to 1
    # instead of accumulating). This directly exercises the real
    # column via the same connection() helper the class itself uses,
    # genuinely simulating "reached the threshold, then time passed,"
    # not a different, accidental behavior.
    with connection(tmp_path / "credentials.db") as conn:
        conn.execute(
            "UPDATE login_attempts SET window_started_at = ? WHERE username = ?",
            ((datetime.now(UTC) - WINDOW - timedelta(seconds=1)).isoformat(), "alice"),
        )
        conn.commit()

    assert tracker.is_locked_out("alice") is False


def test_a_failure_after_the_window_expired_starts_a_fresh_count(tracker, tmp_path: Path):
    for _ in range(MAX_ATTEMPTS):
        tracker.record_failure("alice")

    with connection(tmp_path / "credentials.db") as conn:
        conn.execute(
            "UPDATE login_attempts SET window_started_at = ? WHERE username = ?",
            ((datetime.now(UTC) - WINDOW - timedelta(seconds=1)).isoformat(), "alice"),
        )
        conn.commit()

    # One more failure, now against an expired window -- starts a
    # brand new window/count (1), not (MAX_ATTEMPTS + 1) continuing
    # from the expired one. Confirmed indirectly: MAX_ATTEMPTS - 1
    # MORE failures should still not be enough to lock out again.
    tracker.record_failure("alice")
    for _ in range(MAX_ATTEMPTS - 2):
        tracker.record_failure("alice")
    assert tracker.is_locked_out("alice") is False

    tracker.record_failure("alice")
    assert tracker.is_locked_out("alice") is True
