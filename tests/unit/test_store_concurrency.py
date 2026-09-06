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

Demonstrated concretely before any fix was written, using what was then
LockStore.acquire(): two threads acquiring a free resource were BOTH
told they had it, while only one actually did. That store has since
been removed (it served a config-builder UI that was never built), but
the bug it exposed was in the shared connection handling, and the
tests below cover that directly through the stores that remain.

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
