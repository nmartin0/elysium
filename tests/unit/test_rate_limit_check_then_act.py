"""The rate limit can be exceeded by concurrent callers (001's F-05).

THE GAP, PRECISELY. `record_query()` is already atomic -- it runs in
an immediate transaction and its own comment explains why. What is not
atomic is CHECK-THEN-ACT across the two calls. api/routes.py does:

    if query_rate_limiter.is_rate_limited(user_id):   # transaction 1
        raise HTTPException(429, ...)
    query_rate_limiter.record_query(user_id)          # transaction 2

Between those two lines another caller can check, see the same count,
and be let through. Neither method is wrong; the SEQUENCE is.

THESE TESTS FORCE THE INTERLEAVING, THEY DO NOT RACE FOR IT. RULES.md
3 records why: under the GIL the losing order is rare, so a test that
starts N threads at a barrier and hopes passes against broken code --
which happened three times on this project. The threaded case below
uses Events to pin the exact order A-check, B-check, A-record,
B-record, so both callers are provably inside the window together.

WHAT THESE TESTS ASSERT IS TODAY'S BEHAVIOUR, NOT CORRECT BEHAVIOUR.
They pin a KNOWN, MEASURED GAP so it cannot drift silently while the
fix is scheduled. The fix needs one atomic check-and-record and a
change to api/routes.py, which this agent does not own -- see
REQUESTS_security.md. When that lands, these tests flip from "pins the
overshoot" to "proves it is gone", and the flip is the point: they
fail loudly the moment the behaviour changes, in either direction.
"""

import threading

import pytest

from core.auth.query_rate_limiter import MAX_QUERIES_PER_WINDOW, QueryRateLimiter


@pytest.fixture
def limiter(tmp_path):
    return QueryRateLimiter(tmp_path / "credentials.db")


def _fill_to(limiter: QueryRateLimiter, user_id: str, count: int) -> None:
    for _ in range(count):
        limiter.record_query(user_id)


def _count(limiter: QueryRateLimiter, user_id: str) -> int:
    from core.auth.database import connection

    with connection(limiter._db_path) as conn:
        row = conn.execute(
            "SELECT query_count FROM query_rate_limits WHERE user_id = ?", (user_id,)
        ).fetchone()
    return 0 if row is None else row["query_count"]


def test_the_limit_holds_for_one_caller_at_a_time(limiter):
    """THE OPPOSITE DIRECTION FIRST. Sequentially the limiter is
    correct, so the tests below are about the WINDOW between two
    calls and not about the limiter being broken outright."""
    _fill_to(limiter, "alice", MAX_QUERIES_PER_WINDOW)

    assert limiter.is_rate_limited("alice") is True
    assert _count(limiter, "alice") == MAX_QUERIES_PER_WINDOW


def test_two_callers_both_pass_the_check_before_either_records(limiter):
    """THE GAP, FORCED SEQUENTIALLY. No threads: the interleaving is
    at the CALLER's level, so ordering the four operations by hand is
    both deterministic and a faithful account of what two requests
    do."""
    _fill_to(limiter, "bob", MAX_QUERIES_PER_WINDOW - 1)

    first_check = limiter.is_rate_limited("bob")    # request A checks
    second_check = limiter.is_rate_limited("bob")   # request B checks
    limiter.record_query("bob")                     # A proceeds
    limiter.record_query("bob")                     # B proceeds

    assert first_check is False
    assert second_check is False, "B was refused, so there is no window to exploit"
    assert _count(limiter, "bob") == MAX_QUERIES_PER_WINDOW + 1, (
        "the limit was not exceeded -- check-then-act may have been made atomic, "
        "in which case this test should be rewritten to prove that instead"
    )


def test_the_same_window_with_real_threads_pinned_in_order(limiter):
    """THE SAME GAP WITH REAL THREADS, ordered by Events rather than
    raced. Both callers are provably inside the window together: B
    does not check until A has checked, and A does not record until B
    has checked."""
    _fill_to(limiter, "carol", MAX_QUERIES_PER_WINDOW - 1)

    a_checked = threading.Event()
    b_checked = threading.Event()
    verdicts: dict[str, bool] = {}

    def request_a():
        verdicts["a"] = limiter.is_rate_limited("carol")
        a_checked.set()
        assert b_checked.wait(timeout=5), "B never checked; the order was not forced"
        limiter.record_query("carol")

    def request_b():
        assert a_checked.wait(timeout=5), "A never checked; the order was not forced"
        verdicts["b"] = limiter.is_rate_limited("carol")
        b_checked.set()
        limiter.record_query("carol")

    threads = [threading.Thread(target=request_a), threading.Thread(target=request_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive(), "a thread did not finish; the order deadlocked"

    assert verdicts == {"a": False, "b": False}
    assert _count(limiter, "carol") == MAX_QUERIES_PER_WINDOW + 1


@pytest.mark.parametrize("concurrent", [2, 4, 8])
def test_the_overshoot_is_bounded_by_how_many_check_together(limiter, concurrent):
    """HOW BAD IS IT, MEASURED. The overshoot is not unbounded -- it is
    (callers inside the window) - 1. That matters for how urgently this
    is treated: agent queries run through a pool sized from
    max_concurrent_requests, default 4, so the realistic worst case is
    three queries past the limit rather than an open door."""
    user = f"dave{concurrent}"
    _fill_to(limiter, user, MAX_QUERIES_PER_WINDOW - 1)

    verdicts = [limiter.is_rate_limited(user) for _ in range(concurrent)]
    for _ in range(concurrent):
        limiter.record_query(user)

    assert verdicts == [False] * concurrent
    assert _count(limiter, user) == MAX_QUERIES_PER_WINDOW - 1 + concurrent


def test_record_query_itself_is_atomic(limiter):
    """NOT THE DEFECT, AND WORTH PINNING SO THE FIX DOES NOT UNDO IT.
    Concurrent increments do not lose an update -- record_query runs in
    an immediate transaction. If a future change to close the
    check-then-act window regresses this, the count will come back
    short."""
    _fill_to(limiter, "erin", 0)

    threads = [threading.Thread(target=limiter.record_query, args=("erin",)) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()

    assert _count(limiter, "erin") == 10, "an increment was lost; record_query is not atomic"
