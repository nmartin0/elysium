"""Tests for core/auth/query_rate_limiter.py."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.auth.database import connection
from core.auth.query_rate_limiter import MAX_QUERIES_PER_WINDOW, WINDOW, QueryRateLimiter


@pytest.fixture
def limiter(tmp_path: Path) -> QueryRateLimiter:
    return QueryRateLimiter(tmp_path / "credentials.db")


def test_user_with_no_record_at_all_is_not_rate_limited(limiter):
    assert limiter.is_rate_limited("alice") is False


def test_not_rate_limited_after_fewer_than_max_queries(limiter):
    for _ in range(MAX_QUERIES_PER_WINDOW - 1):
        limiter.record_query("alice")
    assert limiter.is_rate_limited("alice") is False


def test_rate_limited_after_exactly_max_queries(limiter):
    for _ in range(MAX_QUERIES_PER_WINDOW):
        limiter.record_query("alice")
    assert limiter.is_rate_limited("alice") is True


def test_stays_rate_limited_after_further_queries_recorded_anyway(limiter):
    for _ in range(MAX_QUERIES_PER_WINDOW + 3):
        limiter.record_query("alice")
    assert limiter.is_rate_limited("alice") is True


def test_queries_for_one_user_do_not_affect_another(limiter):
    for _ in range(MAX_QUERIES_PER_WINDOW):
        limiter.record_query("alice")

    assert limiter.is_rate_limited("alice") is True
    assert limiter.is_rate_limited("bob") is False


def test_the_limit_expires_once_the_window_has_passed(limiter, tmp_path: Path):
    for _ in range(MAX_QUERIES_PER_WINDOW):
        limiter.record_query("alice")
    assert limiter.is_rate_limited("alice") is True

    # Simulates real time passing by directly backdating the row --
    # NOT by patching WINDOW negative DURING the recording loop above
    # (the same, real mistake login_attempt_tracker.py's own test
    # suite already documents catching itself making: a negative
    # WINDOW makes record_query()'s own "has the window expired" check
    # true on EVERY call, so the count never actually reaches
    # MAX_QUERIES_PER_WINDOW in the first place -- it keeps resetting
    # to 1 instead of accumulating). This directly exercises the real
    # column via the same connection() helper the class itself uses,
    # genuinely simulating "reached the threshold, then time passed,"
    # not a different, accidental behavior.
    with connection(tmp_path / "credentials.db") as conn:
        conn.execute(
            "UPDATE query_rate_limits SET window_started_at = ? WHERE user_id = ?",
            ((datetime.now(UTC) - WINDOW - timedelta(seconds=1)).isoformat(), "alice"),
        )
        conn.commit()

    assert limiter.is_rate_limited("alice") is False


def test_a_query_after_the_window_expired_starts_a_fresh_count(limiter, tmp_path: Path):
    for _ in range(MAX_QUERIES_PER_WINDOW):
        limiter.record_query("alice")

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
    limiter.record_query("alice")
    for _ in range(MAX_QUERIES_PER_WINDOW - 2):
        limiter.record_query("alice")
    assert limiter.is_rate_limited("alice") is False

    limiter.record_query("alice")
    assert limiter.is_rate_limited("alice") is True
