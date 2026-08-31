"""
Tests for core/concurrency.py's KeyedLockManager and ConcurrencyLimiter,
and core/ontology/mediator.py's DataMediator._locks_for_objects() --
the FIRST genuine, multi-threaded proof either mechanism has ever had
anywhere in this project. Everything proving these mechanisms correct
before this file existed did so structurally (the right locks get
acquired, in the right order, by inspection or by a single-threaded
spy) -- never under REAL concurrent contention, on real OS threads,
where a genuine race or deadlock could actually manifest. See core/
ontology/mediator.py's own AI-notes for the tracked history of this
gap, and tests/unit/test_transfer_funds.py for the real, schema-
authored multi-object action (TransferFunds) that finally motivated
closing it.

TIMEOUT-BOUNDED joins throughout, deliberately -- a genuine deadlock
would otherwise hang this file (and the whole test suite run after
it) forever, not just fail. Every thread.join() below has an explicit
timeout, and every assertion checks not thread.is_alive() afterward --
"did this thread actually finish" is the real, meaningful assertion
a deadlock test needs, not merely "no exception was raised."

test_raw_unsorted_acquisition_would_deadlock_without_the_fix is a
DELIBERATE NEGATIVE CONTROL -- proves this file's own detection
methodology (the timeout-bounded join pattern above) actually catches
a real deadlock, not just a tautological pass every test here would
give regardless of whether the real code path works. Bypasses
_locks_for_objects()'s own sorted-order acquisition on purpose,
reproducing the textbook two-thread circular-wait deadlock directly.
If this specific test ever stops finding a deadlock, the detection
methodology itself is broken -- treat that as a reason to distrust
every OTHER test in this file, not evidence the real code got safer.
"""

import threading
import time

import pytest

from core.concurrency import ConcurrencyLimiter, KeyedLockManager
from core.ontology.mediator import DataMediator

JOIN_TIMEOUT = 5.0  # generous for correct code, still bounds a hang


def _minimal_mediator() -> DataMediator:
    # Locking touches NONE of schema/adapters/silo_for_type/roles --
    # a real deployment's worth of setup would be pure, irrelevant
    # weight for what this file actually tests.
    return DataMediator(schema={}, adapters={}, silo_for_type={}, roles={})


def _run_concurrently_tracking_max_holders(context_manager_factories):
    # Shared by every "prove genuine mutual exclusion under real
    # threads" test below -- was near-identical boilerplate
    # (concurrent_holders/max_concurrent_holders/counter_guard, the
    # same worker shape) copied three times before this extraction,
    # caught during a self-review pass over this file's own
    # idiomaticity, matching the same discipline this project already
    # applies elsewhere (e.g. tests/integration/conftest.py's own
    # propose_named_action()).
    #
    # ONE thread per given zero-arg callable, each returning the
    # context manager THAT thread should enter (a bare lock, a
    # ConcurrencyLimiter.limit(), a DataMediator._locks_for_objects()
    # call) -- genuinely different per test, so this stays a factory,
    # not a single shared context manager every thread would enter
    # identically. Returns (max_concurrent_holders, threads) -- the
    # CALLER decides what to assert (deadlock-freedom via thread.
    # is_alive(), mutual exclusion via the count, or both), since
    # different tests care about different combinations.
    concurrent_holders = 0
    max_concurrent_holders = 0
    counter_guard = threading.Lock()  # protects the counters THEMSELVES, a separate concern from what's under test

    def worker(context_manager_factory):
        nonlocal concurrent_holders, max_concurrent_holders
        with context_manager_factory():
            with counter_guard:
                concurrent_holders += 1
                max_concurrent_holders = max(max_concurrent_holders, concurrent_holders)
            time.sleep(0.05)
            with counter_guard:
                concurrent_holders -= 1

    threads = [threading.Thread(target=worker, args=(factory,)) for factory in context_manager_factories]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=JOIN_TIMEOUT)
    return max_concurrent_holders, threads


# --- KeyedLockManager, standalone -------------------------------------------

def test_same_key_returns_the_same_lock_object():
    manager = KeyedLockManager()
    assert manager.lock_for(("Account", "acc_1")) is manager.lock_for(("Account", "acc_1"))


def test_different_keys_return_different_lock_objects():
    manager = KeyedLockManager()
    assert manager.lock_for(("Account", "acc_1")) is not manager.lock_for(("Account", "acc_2"))


def test_keyed_lock_manager_provides_genuine_mutual_exclusion_under_real_threads():
    # THE core, positive proof: 10 real OS threads, all racing for the
    # SAME key, with a real time.sleep() while "inside" to genuinely
    # widen the window a race would need to slip through -- not just
    # asserting the mechanism looks correct by construction.
    manager = KeyedLockManager()
    lock = manager.lock_for(("Account", "acc_1"))

    max_holders, threads = _run_concurrently_tracking_max_holders([lambda: lock] * 10)

    assert all(not t.is_alive() for t in threads), "a thread never finished -- genuine deadlock or hang"
    assert max_holders == 1, f"expected true mutual exclusion (max 1 concurrent holder), saw {max_holders}"


# --- ConcurrencyLimiter, standalone -- also had zero coverage anywhere,
# found while auditing this file for the locking-specific gap; cheap and
# directly related, so closed here too rather than left a second gap. ---

def test_concurrency_limiter_with_no_max_allows_unlimited_concurrency():
    limiter = ConcurrencyLimiter(max_concurrent=None)
    with limiter.limit():
        with limiter.limit():  # would deadlock on a real semaphore of size < 2
            pass  # reaching here at all is the assertion


def test_concurrency_limiter_enforces_a_real_limit_under_genuine_contention():
    limiter = ConcurrencyLimiter(max_concurrent=2)

    max_holders, threads = _run_concurrently_tracking_max_holders([limiter.limit] * 8)

    assert all(not t.is_alive() for t in threads)
    assert max_holders == 2, f"expected the real cap of 2, saw {max_holders}"


# --- DataMediator._locks_for_objects() -- sorted-order deadlock avoidance --

def test_locks_for_objects_prevents_two_threads_holding_a_shared_object_at_once():
    mediator = _minimal_mediator()
    # Genuinely overlapping object sets -- acc_2 is shared, acc_1/acc_3
    # are each unique to one thread. Real contention on the shared one.
    refs_a = [("Account", "acc_1"), ("Account", "acc_2")]
    refs_b = [("Account", "acc_2"), ("Account", "acc_3")]

    max_holders, threads = _run_concurrently_tracking_max_holders([
        lambda: mediator._locks_for_objects(refs_a),
        lambda: mediator._locks_for_objects(refs_b),
    ])

    assert all(not t.is_alive() for t in threads)
    assert max_holders == 1, f"expected true mutual exclusion on the shared object, saw {max_holders}"


def test_locks_for_objects_reverse_caller_order_never_deadlocks():
    # THE key test: two threads each want the SAME two objects, but
    # supply them to _locks_for_objects() in OPPOSITE order -- the
    # textbook setup for a circular-wait deadlock (thread A holds
    # acc_1, wants acc_2; thread B holds acc_2, wants acc_1). Proven
    # safe here NOT because this test is careful about ordering, but
    # because _locks_for_objects() itself sorts internally regardless
    # of what order the caller passes -- exactly the property that
    # makes it safe for two real, independent TransferFunds requests
    # (one A-to-B, one B-to-A) to never deadlock against each other.
    mediator = _minimal_mediator()
    results = []

    def worker(refs):
        with mediator._locks_for_objects(refs):
            results.append(refs)

    thread_a = threading.Thread(target=worker, args=([("Account", "acc_1"), ("Account", "acc_2")],))
    thread_b = threading.Thread(target=worker, args=([("Account", "acc_2"), ("Account", "acc_1")],))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=JOIN_TIMEOUT)
    thread_b.join(timeout=JOIN_TIMEOUT)

    assert not thread_a.is_alive() and not thread_b.is_alive(), (
        "a thread never finished -- _locks_for_objects() deadlocked under reverse-order contention"
    )
    assert len(results) == 2


@pytest.mark.parametrize("_attempt", range(3))
def test_locks_for_objects_reverse_caller_order_never_deadlocks_repeated(_attempt):
    # Deadlock timing is inherently racy -- a single pass proves it's
    # POSSIBLE to avoid, not that it's reliably avoided. Repeated
    # (fresh mediator/threads each time, matching pytest's own
    # function-scoped default) to make a flaky, timing-dependent
    # false negative in the single-pass version above genuinely
    # unlikely to slip through unnoticed.
    mediator = _minimal_mediator()

    def worker(refs):
        with mediator._locks_for_objects(refs):
            pass

    thread_a = threading.Thread(target=worker, args=([("Account", "acc_1"), ("Account", "acc_2")],))
    thread_b = threading.Thread(target=worker, args=([("Account", "acc_2"), ("Account", "acc_1")],))
    thread_a.start()
    thread_b.start()
    thread_a.join(timeout=JOIN_TIMEOUT)
    thread_b.join(timeout=JOIN_TIMEOUT)

    assert not thread_a.is_alive() and not thread_b.is_alive()


def test_raw_unsorted_acquisition_would_deadlock_without_the_fix():
    # NEGATIVE CONTROL -- see this file's own module docstring for the
    # full reasoning. Deliberately bypasses _locks_for_objects()'s own
    # sorting, acquiring the SAME two real locks directly, each thread
    # in the OPPOSITE order -- proving this file's timeout-bounded-join
    # methodology genuinely detects a deadlock when one exists, not
    # just when the real, correct code happens to avoid one.
    manager = KeyedLockManager()
    lock_1 = manager.lock_for(("Account", "acc_1"))
    lock_2 = manager.lock_for(("Account", "acc_2"))
    ready = threading.Barrier(2, timeout=JOIN_TIMEOUT)

    def worker_a():
        with lock_1:
            ready.wait()  # both threads hold their FIRST lock before either tries their second
            with lock_2:
                pass

    def worker_b():
        with lock_2:
            ready.wait()
            with lock_1:
                pass

    # daemon=True is NOT optional here -- these two threads are
    # EXPECTED to deadlock and never finish, permanently, for the rest
    # of the process's life. A real, confirmed problem found by
    # actually running this without it: a non-daemon thread that never
    # finishes prevents the whole Python process from exiting at all,
    # hanging the entire test suite run after this test's own
    # assertion already passed -- not a hypothetical, reproduced
    # directly (a bare subprocess run of just this test hung past
    # 30s with plain, non-daemon threads).
    thread_a = threading.Thread(target=worker_a, daemon=True)
    thread_b = threading.Thread(target=worker_b, daemon=True)
    thread_a.start()
    thread_b.start()
    # A SHORT timeout here, deliberately -- this test EXPECTS the
    # deadlock to still be in progress when it checks, not waiting out
    # the same generous budget the positive tests above use.
    thread_a.join(timeout=1.0)
    thread_b.join(timeout=1.0)

    assert thread_a.is_alive() and thread_b.is_alive(), (
        "expected a genuine deadlock here (the whole point of this negative control) -- "
        "if both threads actually finished, this file's own detection methodology is not "
        "trustworthy, and every OTHER test in this file needs re-examining, not just this one"
    )


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - test_raw_unsorted_acquisition_would_deadlock_without_the_fix's own
#   two intentionally-deadlocked threads originally had NO daemon=True
#   -- a real bug, found by actually running the negative control in
#   isolation (a bare subprocess, no external timeout wrapper), not
#   assumed safe by construction: the two permanently-blocked, non-
#   daemon threads silently prevented the whole Python process from
#   ever exiting, hanging past 30s even though the test's own
#   assertion had already passed. Every test run in-process alongside
#   this one (the fast suite as a whole) was equally at risk, not just
#   this file run alone -- confirmed fixed the same way, a bare
#   subprocess run of the fast suite completing and exiting cleanly.
#
# DEFERRED (known, intentional, not yet built):
# - Every test here uses DataMediator's OWN locking directly
#   (_lock_for_object()/_locks_for_objects()), not a full, real
#   confirm_and_execute() call under genuine multi-threaded contention
#   -- e.g. two REAL, concurrent TransferFunds requests (see tests/
#   unit/test_transfer_funds.py) whose own account sets genuinely
#   overlap, racing through the WHOLE write path, not just the locking
#   primitive in isolation. This file proves the underlying mechanism
#   is sound; a full-stack concurrent-write test would be a separate,
#   larger piece of work, not attempted here.
