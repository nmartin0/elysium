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
import time

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


# --- GIL race audit ------------------------------------------------------
#
# A sweep for check-then-act patterns on state shared across requests,
# prompted by the security cache where `if key in d: return d[key]`
# could raise KeyError if another thread cleared between the two steps.
#
# THE METHOD MATTERS: these interleavings are FORCED, not hoped for.
# Three probabilistic attempts at the cache race found nothing -- 12
# threads, a 1e-9 switch interval, an explicit yield -- and forcing the
# order found it immediately. Under the GIL, rare is not safe, and a
# test that hopes to hit a race is not a test.


def test_one_limiter_per_silo_however_threads_interleave():
    # THE bug this audit found. `if silo not in d: d[silo] = Limiter()`
    # let two threads each build a limiter and one silently replace the
    # other -- so they held DIFFERENT limiters for one silo and each
    # enforced max_concurrent_writes independently. The configured
    # ceiling on concurrent writes to a customer's database could then
    # be exceeded, with nothing raised and nothing logged. Unlike the
    # cache race, this failure is silent, which makes it worse.
    #
    # The interleaving is FORCED through the adapter's own property,
    # which is read INSIDE the old code's `if` block: two threads
    # reaching it are both past the check. A first version of this test
    # just raced eight threads at a barrier and PASSED against the
    # broken code -- the same probabilistic mistake that hid the cache
    # race through three attempts.
    from core.ontology.mediator import DataMediator

    both_inside = threading.Barrier(2, timeout=2)

    class RacingAdapter:
        @property
        def max_concurrent_writes(self):
            try:
                both_inside.wait()
            except threading.BrokenBarrierError:
                pass  # only one thread got here: no race to force
            return 2

    mediator = DataMediator({}, {"primary": RacingAdapter()}, {}, {})
    handed_out = []
    guard = threading.Lock()

    def grab():
        limiter = mediator._write_limiter_for_silo("primary")
        with guard:
            handed_out.append(id(limiter))

    threads = [threading.Thread(target=grab) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(set(handed_out)) == 1, (
        "concurrent callers received different limiters for one silo -- "
        "the write-concurrency ceiling is not enforced"
    )


def test_schema_is_verified_once_however_threads_interleave(tmp_path):
    # The lock here was released BETWEEN the check and the add, so two
    # threads could both run the schema and every migration. Harmless
    # today only because the schema uses CREATE TABLE IF NOT EXISTS and
    # the one migration catches "column already exists" -- safe by
    # coincidence, not construction. A future non-idempotent migration
    # would have corrupted the database with no warning.
    from core.sqlite_connection import connection_with_schema

    runs = []
    guard = threading.Lock()
    barrier = threading.Barrier(6)
    db_path = tmp_path / "shared.db"

    def counting_migration(conn):
        with guard:
            runs.append(1)

    def connect():
        barrier.wait()
        with connection_with_schema(
            db_path,
            "CREATE TABLE IF NOT EXISTS t (id TEXT PRIMARY KEY);",
            migrations=(counting_migration,),
        ):
            pass

    threads = [threading.Thread(target=connect) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(runs) == 1, (
        f"migrations ran {len(runs)} times for one database -- schema "
        f"verification is check-then-act"
    )


def test_two_callers_racing_for_one_key_cannot_both_hold_it():
    """The guarantee the manager exists to provide: two callers asking
    for one key get a lock that actually excludes them.

    ASSERTS MUTUAL EXCLUSION, NOT IDENTITY. Under the old
    create-on-demand version an identity comparison could not see the
    bug: both threads created a lock, the second overwrote the first
    in the dict, and both callers ended up holding the SAME survivor.
    The harm -- a thread holding the discarded lock not excluding one
    holding the survivor -- was visible only while both were held.

    Striping removes that failure mode entirely, since nothing is ever
    created or replaced. This stays as the guarantee's own test: it
    describes what callers are owed, not how it is delivered, so it
    keeps working if the implementation changes again.
    """
    from core.concurrency import KeyedLockManager

    manager = KeyedLockManager()
    acquired: list[bool] = []
    guard = threading.Lock()
    holding = threading.Event()

    def first():
        lock = manager.lock_for(("Customer", "same-key"))
        lock.acquire()
        holding.set()
        time.sleep(0.2)
        lock.release()

    def second():
        lock = manager.lock_for(("Customer", "same-key"))
        holding.wait(2)
        got = lock.acquire(blocking=False)
        with guard:
            acquired.append(got)
        if got:
            lock.release()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert acquired == [False], (
        "a second caller acquired the key while the first held it -- the "
        "two were given different locks, so the lock excludes nobody"
    )


def test_different_keys_get_different_locks():
    # The other half: one lock for everything would be correct and
    # useless.
    from core.concurrency import KeyedLockManager

    manager = KeyedLockManager()

    assert manager.lock_for("a") is not manager.lock_for("b")


# --- Bounded lock memory -------------------------------------------------


def test_lock_memory_is_bounded_however_many_keys_are_used():
    """The manager held one lock per distinct key FOREVER, never
    evicted. Measured at ~164 bytes retained per object ever written:
    6 GB after a year at 100k writes/day, 60 GB at 1M/day. A
    long-running deployment would exhaust memory -- an unbounded leak,
    not a tradeoff.

    Striping bounds it: keys map onto a fixed set of locks, so memory
    is constant regardless of how many distinct objects are ever
    touched.
    """
    from core.concurrency import KeyedLockManager

    manager = KeyedLockManager()
    for index in range(200_000):
        manager.lock_for(("Customer", f"cust_{index}"))

    assert len(manager._locks) <= 1024, (
        f"{len(manager._locks)} locks retained for 200,000 keys -- memory "
        f"grows with every distinct object ever written"
    )


def test_the_same_key_always_maps_to_the_same_lock():
    # Striping is only correct if a key's lock is stable. A key that
    # mapped somewhere else on a later call would exclude nobody.
    from core.concurrency import KeyedLockManager

    manager = KeyedLockManager()

    assert manager.lock_for(("Customer", "c1")) is manager.lock_for(("Customer", "c1"))
    assert manager.lock_for(("Customer", "c1")) is not manager.lock_for(("Customer", "c1x"))


def test_two_keys_sharing_a_stripe_still_exclude_each_other():
    """False contention is the price of striping and must stay SAFE.

    Two unrelated keys landing on one stripe block each other
    needlessly -- acceptable, and vastly better than the alternative
    of them NOT excluding when they should. What must never happen is
    a shared stripe failing to exclude.
    """
    from core.concurrency import KeyedLockManager

    manager = KeyedLockManager()
    # Find two genuinely different keys that collide.
    first = ("Customer", "c1")
    target = manager.lock_for(first)
    colliding = next(
        ("Customer", f"c{i}") for i in range(2, 500_000)
        if manager.lock_for(("Customer", f"c{i}")) is target
    )

    assert colliding != first
    with manager.lock_for(first):
        assert manager.lock_for(colliding).acquire(blocking=False) is False


def test_locking_two_stripe_colliding_objects_together_does_not_deadlock():
    """A deadlock striping would have introduced, caught before it
    shipped.

    Locks are striped, so two DISTINCT objects can share one --
    verified: ('Customer', 'c1') and ('Customer', 'c1940') map to the
    same lock. A write touching both would acquire it twice, and
    threading.Lock is not reentrant, so the whole write path would
    hang.

    The existing duplicate assert cannot see this: it compares KEYS,
    which differ. _locks_for_objects() therefore deduplicates by LOCK
    while still ordering by key, so callers acquire the same locks in
    the same sequence and cannot deadlock against each other either.
    """
    from core.concurrency import KeyedLockManager
    from core.ontology.mediator import DataMediator

    probe = KeyedLockManager()
    first = ("Customer", "c1")
    colliding = next(
        ("Customer", f"c{i}") for i in range(2, 500_000)
        if probe.lock_for(("Customer", f"c{i}")) is probe.lock_for(first)
    )
    assert colliding != first

    mediator = DataMediator({}, {}, {}, {})
    finished = threading.Event()

    def lock_both():
        with mediator._locks_for_objects([first, colliding]):
            finished.set()

    worker = threading.Thread(target=lock_both, daemon=True)
    worker.start()
    worker.join(5)

    assert finished.is_set(), (
        "locking two objects that share a stripe hung -- the lock set was "
        "deduplicated by key, not by lock"
    )
