"""Tests for core/auth/login_attempt_tracker.py."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.auth.database import connection
from core.auth.login_attempt_tracker import (
    MAX_ATTEMPTS,
    WINDOW,
    LoginAttemptReader,
    LoginAttemptWriter,
)


@pytest.fixture
def reader(tmp_path: Path) -> LoginAttemptReader:
    # Schema explicitly ensured here, before the Reader is ever
    # constructed -- a real, necessary step, not defensive boilerplate:
    # a genuinely read-only connection can never create the
    # login_attempts table itself (see core/auth/login_attempt_tracker.py's
    # own module docstring), so a test exercising the Reader alone,
    # with no prior write, would otherwise fail on "no such table" --
    # the exact real ordering requirement api/app.py's own explicit
    # startup step exists to guarantee in production.
    db_path = tmp_path / "credentials.db"
    with connection(db_path):
        pass
    return LoginAttemptReader(db_path)


@pytest.fixture
def writer(tmp_path: Path) -> LoginAttemptWriter:
    return LoginAttemptWriter(tmp_path / "credentials.db")


def test_username_with_no_record_at_all_is_not_locked_out(reader):
    assert reader.is_locked_out("alice") is False


def test_not_locked_out_after_fewer_than_max_failures(reader, writer):
    for _ in range(MAX_ATTEMPTS - 1):
        writer.record_failure("alice")
    assert reader.is_locked_out("alice") is False


def test_locked_out_after_exactly_max_failures(reader, writer):
    for _ in range(MAX_ATTEMPTS):
        writer.record_failure("alice")
    assert reader.is_locked_out("alice") is True


def test_locked_out_stays_locked_out_after_further_failures(reader, writer):
    for _ in range(MAX_ATTEMPTS + 3):
        writer.record_failure("alice")
    assert reader.is_locked_out("alice") is True


def test_record_success_clears_a_prior_lockout(reader, writer):
    for _ in range(MAX_ATTEMPTS):
        writer.record_failure("alice")
    assert reader.is_locked_out("alice") is True

    writer.record_success("alice")

    assert reader.is_locked_out("alice") is False


def test_record_success_with_no_prior_record_does_not_raise(writer):
    writer.record_success("alice")  # does not raise


def test_failures_for_one_username_do_not_affect_another(reader, writer):
    for _ in range(MAX_ATTEMPTS):
        writer.record_failure("alice")

    assert reader.is_locked_out("alice") is True
    assert reader.is_locked_out("bob") is False


def test_lockout_expires_once_the_window_has_passed(reader, writer, tmp_path: Path):
    for _ in range(MAX_ATTEMPTS):
        writer.record_failure("alice")
    assert reader.is_locked_out("alice") is True

    # Simulates real time passing by directly backdating the row --
    # NOT by patching WINDOW negative DURING the recording loop above
    # (a real mistake caught while writing this test: a negative
    # WINDOW makes record_failure()'s own "has the window expired"
    # check true on EVERY call, so the count never actually reaches
    # MAX_ATTEMPTS in the first place -- it keeps resetting to 1
    # instead of accumulating). This directly exercises the real
    # column via the same connection() helper the Writer itself uses,
    # genuinely simulating "reached the threshold, then time passed,"
    # not a different, accidental behavior.
    with connection(tmp_path / "credentials.db") as conn:
        conn.execute(
            "UPDATE login_attempts SET window_started_at = ? WHERE username = ?",
            ((datetime.now(UTC) - WINDOW - timedelta(seconds=1)).isoformat(), "alice"),
        )
        conn.commit()

    assert reader.is_locked_out("alice") is False


def test_a_failure_after_the_window_expired_starts_a_fresh_count(reader, writer, tmp_path: Path):
    for _ in range(MAX_ATTEMPTS):
        writer.record_failure("alice")

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
    writer.record_failure("alice")
    for _ in range(MAX_ATTEMPTS - 2):
        writer.record_failure("alice")
    assert reader.is_locked_out("alice") is False

    writer.record_failure("alice")
    assert reader.is_locked_out("alice") is True


def test_reader_connection_is_structurally_read_only(reader, writer):
    # A real, direct proof of the actual, new safety property this
    # split exists for -- not just "the tests still pass with two
    # objects instead of one." Confirmed directly, empirically: a real
    # attempt to write through the Reader's own connection is denied
    # at the SQLite engine level itself, not merely unused by this
    # class's own methods.
    writer.record_failure("alice")  # ensures the table exists first
    with reader._connection() as conn, pytest.raises(Exception, match="not authorized"):
        conn.execute("UPDATE login_attempts SET failed_count = 999 WHERE username = 'alice'")
