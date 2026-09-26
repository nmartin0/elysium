"""Checking and recording a query happen in one transaction (F-05).

THE DEFECT. `record_query()` was already atomic -- its own comment
explains why. What was not atomic was the SEQUENCE in api/routes.py:

    if query_rate_limiter.is_rate_limited(user_id):   # transaction 1
        raise HTTPException(429, ...)
    query_rate_limiter.record_query(user_id)          # transaction 2

Another caller checks between those two lines, sees the same count,
and is let through. Neither method is wrong; the sequence is.

MEASURED, in tests/unit/test_rate_limit_check_then_act.py, which pins
the OLD behaviour: at 19 of 20, two callers both check, both pass,
both record, and the count reaches 21. That file is the "before"; this
one is the "after", and BOTH are kept -- the old one still describes
what the two-call sequence does, which is true until the route
changes.

THE ROUTE STILL HAS TO CHANGE. `try_record_query()` has no production
caller yet: api/routes.py:3378-3380 is backend's file and the swap is
filed in REQUESTS_security.md. Until then this is exercised by tests
only, which vulture counts (its paths include `tests`).

WHICH TEST IS PRIMARY -- I HAD THIS BACKWARDS, and the control said
so. I first labelled the sequential test primary and the threaded one
supplementary, reasoning that the interleaving is at the caller's
level. Then I ran the control that reimplements try_record_query as
the old two-call sequence, and:

    non-atomic implementation -> 1 failed, 8 passed
      the ONLY failure was the THREADED test

The sequential test passed against the broken version, because two
calls made one after the other never interleave: the first records
before the second checks. It could not have caught this. The threaded
test is the primary behavioural one, and
test_the_read_and_write_share_one_transaction below is the
deterministic guard, pinned at source because the mechanism is what
matters and no sequential call can observe it.

That is RULES.md 3 working in the direction it warns about -- not "a
test that cannot fail", but a test I had wrongly ranked.
"""

import inspect
import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from core.auth.query_rate_limiter import MAX_QUERIES_PER_WINDOW as CAP
from core.auth.query_rate_limiter import QueryRateLimiter


@pytest.fixture
def limiter():
    return QueryRateLimiter(Path(tempfile.mkdtemp()) / "credentials.db")


def _count(limiter, user_id="alice") -> int:
    with sqlite3.connect(limiter._db_path) as conn:
        row = conn.execute(
            "SELECT query_count FROM query_rate_limits WHERE user_id = ?", (user_id,)
        ).fetchone()
    return 0 if row is None else row[0]


class TestTheLimitHolds:
    def test_the_first_calls_are_allowed_and_the_rest_refused(self, limiter):
        verdicts = [limiter.try_record_query("alice") for _ in range(CAP + 3)]

        assert verdicts[:CAP] == [True] * CAP
        assert verdicts[CAP:] == [False] * 3

    def test_a_refused_call_does_not_increment(self, limiter):
        """A refused query cost no model call, so counting it would
        extend the lockout for work that never happened -- and would
        let a client that keeps retrying hold its window open."""
        for _ in range(CAP + 10):
            limiter.try_record_query("alice")

        assert _count(limiter) == CAP

    def test_two_callers_in_the_window_cannot_both_pass(self, limiter):
        """THE DEFECT, FORCED. This is the exact shape that overshoots
        through the two-call sequence: at CAP-1, two callers arrive.
        Through one atomic call the second must be refused."""
        for _ in range(CAP - 1):
            limiter.try_record_query("alice")

        first = limiter.try_record_query("alice")
        second = limiter.try_record_query("alice")

        assert (first, second) == (True, False)
        assert _count(limiter) == CAP, "the limit was exceeded"

    def test_the_two_call_sequence_still_overshoots_where_this_does_not(self, limiter):
        """THE COMPARISON, in one place, so the fix is visible rather
        than asserted. The old sequence is still reachable and still
        wrong; that is why the route has to change too."""
        for _ in range(CAP - 1):
            limiter.try_record_query("alice")

        # The old shape: both check before either records.
        old_first = not limiter.is_rate_limited("alice")
        old_second = not limiter.is_rate_limited("alice")
        limiter.record_query("alice")
        limiter.record_query("alice")

        assert (old_first, old_second) == (True, True)
        assert _count(limiter) == CAP + 1, "the old sequence no longer overshoots"


class TestWhatMustStillWork:
    """THE OPPOSITE DIRECTION. A limiter that refused everything would
    satisfy the tests above and break the product."""

    def test_an_unknown_user_is_allowed(self, limiter):
        assert limiter.try_record_query("newcomer") is True

    def test_under_the_cap_everything_passes(self, limiter):
        assert all(limiter.try_record_query("alice") for _ in range(CAP))

    def test_users_have_separate_budgets(self, limiter):
        for _ in range(CAP):
            limiter.try_record_query("alice")

        assert limiter.try_record_query("bob") is True

    def test_an_expired_window_starts_fresh(self, limiter):
        """Not an ever-growing count from a much earlier, unrelated
        burst -- the same reasoning record_query already follows."""
        for _ in range(CAP):
            limiter.try_record_query("alice")
        with sqlite3.connect(limiter._db_path) as conn:
            conn.execute("UPDATE query_rate_limits SET window_started_at = ?",
                         ("2020-01-01T00:00:00+00:00",))
            conn.commit()

        assert limiter.try_record_query("alice") is True
        assert _count(limiter) == 1


def test_the_read_and_write_share_one_transaction(limiter):
    """THE DETERMINISTIC GUARD, pinned at source.

    Atomicity is a property of the MECHANISM, and no sequential call
    can observe it -- the control proved that by passing against a
    non-atomic implementation. AGENTS.md sanctions a source-level
    tripwire for exactly this case, where a behavioural control cannot
    work, provided the test says why.

    So: try_record_query must do its SELECT and its UPDATE inside one
    immediate_transaction. If a later refactor splits them -- which is
    precisely how F-05 arose one layer up -- this fails even when the
    threads happen to schedule kindly.
    """
    source = inspect.getsource(QueryRateLimiter.try_record_query)

    assert "immediate_transaction(conn)" in source, (
        "try_record_query no longer opens an immediate transaction; a read and a "
        "write outside one is the check-then-act F-05 was about"
    )
    assert source.count("with connection(") == 1, (
        "more than one connection is opened, so the read and the write can be in "
        "different transactions"
    )
    assert "self.is_rate_limited(" not in source, (
        "try_record_query delegates to is_rate_limited, which reopens the very "
        "two-transaction sequence it exists to replace"
    )


def test_concurrent_callers_never_exceed_the_cap(limiter):
    """THE PRIMARY BEHAVIOURAL TEST, and the only one that caught the
    non-atomic implementation when it was controlled.

    It asserts an invariant that must hold under EVERY interleaving:
    however the threads are scheduled, exactly CAP calls are allowed
    and the stored count is exactly CAP. Overshoot shows as more than
    CAP allowed; a lost update shows as a count below it.
    """
    verdicts = []
    lock = threading.Lock()

    def call():
        allowed = limiter.try_record_query("alice")
        with lock:
            verdicts.append(allowed)

    threads = [threading.Thread(target=call) for _ in range(CAP + 10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive(), "a caller deadlocked"

    assert sum(verdicts) == CAP, f"{sum(verdicts)} allowed, cap is {CAP}"
    assert _count(limiter) == CAP
