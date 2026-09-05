"""Tests for core/auth/query_rate_limiter.py."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.auth.database import connection
from core.auth.query_rate_limiter import (
    MAX_QUERIES_PER_WINDOW,
    WINDOW,
    QueryRateLimitReader,
    QueryRateLimitWriter,
)


@pytest.fixture
def reader(tmp_path: Path) -> QueryRateLimitReader:
    # Schema explicitly ensured here, before the Reader is ever
    # constructed -- a real, necessary step, not defensive boilerplate:
    # a genuinely read-only connection can never create the
    # query_rate_limits table itself (see core/auth/query_rate_limiter.py's
    # own module docstring), so a test exercising the Reader alone,
    # with no prior write, would otherwise fail on "no such table" --
    # the exact real ordering requirement api/app.py's own explicit
    # startup step exists to guarantee in production.
    db_path = tmp_path / "credentials.db"
    with connection(db_path):
        pass
    return QueryRateLimitReader(db_path)


@pytest.fixture
def writer(tmp_path: Path) -> QueryRateLimitWriter:
    return QueryRateLimitWriter(tmp_path / "credentials.db")


def test_user_with_no_record_at_all_is_not_rate_limited(reader):
    assert reader.is_rate_limited("alice") is False


def test_not_rate_limited_after_fewer_than_max_queries(reader, writer):
    for _ in range(MAX_QUERIES_PER_WINDOW - 1):
        writer.record_query("alice")
    assert reader.is_rate_limited("alice") is False


def test_rate_limited_after_exactly_max_queries(reader, writer):
    for _ in range(MAX_QUERIES_PER_WINDOW):
        writer.record_query("alice")
    assert reader.is_rate_limited("alice") is True


def test_stays_rate_limited_after_further_queries_recorded_anyway(reader, writer):
    for _ in range(MAX_QUERIES_PER_WINDOW + 3):
        writer.record_query("alice")
    assert reader.is_rate_limited("alice") is True


def test_queries_for_one_user_do_not_affect_another(reader, writer):
    for _ in range(MAX_QUERIES_PER_WINDOW):
        writer.record_query("alice")

    assert reader.is_rate_limited("alice") is True
    assert reader.is_rate_limited("bob") is False


def test_the_limit_expires_once_the_window_has_passed(reader, writer, tmp_path: Path):
    for _ in range(MAX_QUERIES_PER_WINDOW):
        writer.record_query("alice")
    assert reader.is_rate_limited("alice") is True

    # Simulates real time passing by directly backdating the row --
    # NOT by patching WINDOW negative DURING the recording loop above
    # (the same, real mistake login_attempt_tracker.py's own test
    # suite already documents catching itself making: a negative
    # WINDOW makes record_query()'s own "has the window expired" check
    # true on EVERY call, so the count never actually reaches
    # MAX_QUERIES_PER_WINDOW in the first place -- it keeps resetting
    # to 1 instead of accumulating). This directly exercises the real
    # column via the same connection() helper the Writer itself uses,
    # genuinely simulating "reached the threshold, then time passed,"
    # not a different, accidental behavior.
    with connection(tmp_path / "credentials.db") as conn:
        conn.execute(
            "UPDATE query_rate_limits SET window_started_at = ? WHERE user_id = ?",
            ((datetime.now(UTC) - WINDOW - timedelta(seconds=1)).isoformat(), "alice"),
        )
        conn.commit()

    assert reader.is_rate_limited("alice") is False


def test_a_query_after_the_window_expired_starts_a_fresh_count(reader, writer, tmp_path: Path):
    for _ in range(MAX_QUERIES_PER_WINDOW):
        writer.record_query("alice")

    with connection(tmp_path / "credentials.db") as conn:
        conn.execute(
            "UPDATE query_rate_limits SET window_started_at = ? WHERE user_id = ?",
            ((datetime.now(UTC) - WINDOW - timedelta(seconds=1)).isoformat(), "alice"),
        )
        conn.commit()

    # One more query, now against an expired window -- starts a brand
    # new window/count (1), not (MAX_QUERIES_PER_WINDOW + 1) continuing
    # from the expired one. Confirmed indirectly: MAX_QUERIES_PER_
    # WINDOW - 1 MORE queries should still not be enough to trigger
    # the limit again.
    writer.record_query("alice")
    for _ in range(MAX_QUERIES_PER_WINDOW - 2):
        writer.record_query("alice")
    assert reader.is_rate_limited("alice") is False

    writer.record_query("alice")
    assert reader.is_rate_limited("alice") is True


def test_reader_connection_is_structurally_read_only(reader, writer):
    # A real, direct proof of the actual, new safety property this
    # split exists for -- not just "the tests still pass with two
    # objects instead of one." Confirmed directly, empirically: a real
    # attempt to write through the Reader's own connection is denied
    # at the SQLite engine level itself, not merely unused by this
    # class's own methods.
    writer.record_query("alice")  # ensures the table exists first
    with reader._connection() as conn, pytest.raises(Exception, match="not authorized"):
        conn.execute("UPDATE query_rate_limits SET query_count = 999 WHERE user_id = 'alice'")
