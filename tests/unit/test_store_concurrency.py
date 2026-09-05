"""
Real concurrency tests for the internal stores' read-modify-write
sequences.

WHY THIS FILE EXISTS. An audit of the internal stores found a genuine,
reproducible race, not a theoretical one: Python's sqlite3 defaults to
isolation_level='', which opens a transaction lazily on the first
INSERT/UPDATE/DELETE -- never on a SELECT. So every "read current
state, decide, then write" sequence had its READ outside any
transaction, and two concurrent callers could both read the same
pre-state and both act on it.

Demonstrated concretely before any fix was written: two threads calling
LockStore.acquire() against a free resource were BOTH told they had
acquired it, while only one actually held it afterwards. A lock service
that grants the same lock twice does not do its job.

The existing suite never caught this because every test was
single-threaded. These tests are deliberately concurrent, with a real
threading.Barrier forcing both callers to have completed their READ
before either WRITES -- which is exactly the interleaving that made the
bug appear, and which random timing would only hit occasionally.
"""

import sqlite3
import threading

import pytest

from core.auth.login_attempt_tracker import MAX_ATTEMPTS, LoginAttemptTracker
from core.auth.query_rate_limiter import MAX_QUERIES_PER_WINDOW, QueryRateLimiter
from core.lock_store import LockStore


def _run_concurrently(fn, count):
    """Runs fn(i) in `count` threads, forcing them to reach the
    critical section together rather than relying on lucky timing."""
    barrier = threading.Barrier(count)
    results = []
    lock = threading.Lock()

    def worker(i):
        barrier.wait()
        result = fn(i)
        with lock:
            results.append(result)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# Repeated across many trials, deliberately. The race is REAL but
# INTERMITTENT -- it needs both threads to complete their SELECT before
# either INSERTs, which a single trial hits only sometimes. Measured
# directly against the unfixed code: 7 of 200 trials granted the same
# lock to both callers. A one-shot test passed against the broken
# implementation, which is exactly how this bug survived the existing
# suite in the first place.
_RACE_TRIALS = 60


def test_two_concurrent_acquirers_never_both_get_the_same_lock(tmp_path):
    # THE bug this audit found. Before the fix, both callers were
    # sometimes told they had acquired it.
    for trial in range(_RACE_TRIALS):
        store = LockStore(tmp_path / f"locks_{trial}.db")

        results = _run_concurrently(
            lambda i, s=store: s.acquire("shared_resource", f"user_{i}"), count=2
        )

        granted = [r for r in results if r is not None]
        assert len(granted) == 1, (
            f"trial {trial}: exactly one caller may acquire, got {len(granted)}"
        )
        assert store.get_status("shared_resource") is not None


def test_many_concurrent_acquirers_still_yield_exactly_one_holder(tmp_path):
    for trial in range(_RACE_TRIALS):
        store = LockStore(tmp_path / f"many_{trial}.db")
        results = _run_concurrently(
            lambda i, s=store: s.acquire("shared_resource", f"user_{i}"), count=8
        )
        assert sum(1 for r in results if r is not None) == 1, f"trial {trial}"


def test_the_same_user_reacquiring_concurrently_is_not_treated_as_contention(tmp_path):
    # A real, legitimate case: one user with two browser tabs. Both may
    # succeed -- acquire() deliberately allows the SAME user to
    # re-acquire (see its own docstring) -- but the store must stay
    # consistent rather than corrupt.
    store = LockStore(tmp_path / "locks.db")

    results = _run_concurrently(lambda i: store.acquire("r", "same_user"), count=4)

    assert all(r is not None for r in results)
    assert store.get_status("r") is not None


def test_concurrent_failed_logins_are_not_undercounted(tmp_path):
    # Without an immediate transaction, two threads read the same count
    # and both write count+1 as the SAME value -- silently losing a
    # failure, which for a brute-force limiter means allowing more
    # attempts than configured.
    tracker = LoginAttemptTracker(tmp_path / "credentials.db")

    _run_concurrently(lambda i: tracker.record_failure("alice"), count=MAX_ATTEMPTS)

    assert tracker.is_locked_out("alice") is True


def test_concurrent_queries_are_not_undercounted(tmp_path):
    # Same hazard, same real consequence: a rate limiter that
    # undercounts lets through more than its configured limit.
    limiter = QueryRateLimiter(tmp_path / "credentials.db")

    _run_concurrently(lambda i: limiter.record_query("alice"), count=MAX_QUERIES_PER_WINDOW)

    assert limiter.is_rate_limited("alice") is True


def test_a_failing_transaction_rolls_back_rather_than_half_applying(tmp_path):
    # immediate_transaction() must genuinely roll back on an exception,
    # not leave a partial write behind.
    from core.sqlite_connection import immediate_transaction, open_connection

    db_path = tmp_path / "t.db"
    conn = open_connection(db_path)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    conn.close()

    conn = open_connection(db_path)
    with pytest.raises(RuntimeError):
        with immediate_transaction(conn):
            conn.execute("INSERT INTO t VALUES ('a', '1')")
            raise RuntimeError("something went wrong mid-transaction")
    conn.close()

    conn = open_connection(db_path)
    assert conn.execute("SELECT count(*) FROM t").fetchone()[0] == 0
    conn.close()


def test_the_connection_isolation_level_is_restored_afterwards(tmp_path):
    # The helper changes isolation_level to take explicit control; it
    # must hand the connection back as it found it, or an unrelated
    # later caller on the same connection behaves differently.
    from core.sqlite_connection import immediate_transaction, open_connection

    db_path = tmp_path / "t.db"
    conn = open_connection(db_path)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
    conn.commit()
    before = conn.isolation_level

    with immediate_transaction(conn):
        conn.execute("INSERT INTO t VALUES ('a')")

    assert conn.isolation_level == before
    conn.close()


def test_a_second_writer_blocks_rather_than_reading_stale_state(tmp_path):
    # The mechanism itself: BEGIN IMMEDIATE takes SQLite's write lock up
    # front, so a second transaction cannot start until the first
    # commits. Proven directly rather than inferred from the absence of
    # a race above.
    from core.sqlite_connection import immediate_transaction, open_connection

    db_path = tmp_path / "t.db"
    setup = open_connection(db_path)
    setup.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
    setup.commit()
    setup.close()

    first = open_connection(db_path)
    second = sqlite3.connect(db_path, timeout=0.1)

    with immediate_transaction(first):
        first.execute("INSERT INTO t VALUES ('a')")
        # While the first transaction holds the write lock, a second
        # writer genuinely cannot proceed.
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            second.execute("BEGIN IMMEDIATE")

    second.close()
    first.close()
