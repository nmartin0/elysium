"""
concurrency.py  (generic concurrency primitive -- zero knowledge of
data silos, LLMs, or tools)

ConcurrencyLimiter wraps a semaphore, but is None-aware: max_concurrent
of None means "no limit needed" as a real, first-class case, not an
error or a magic sentinel number. This is what lets every declaring
surface (DataSiloAdapter.max_concurrent_writes, LLMAdapter.
max_concurrent_requests, Tool.max_concurrent_calls) share one identical
mechanism rather than three separate implementations of the same idea.

This solves RESOURCE CAPACITY problems only ("this backend can only
physically handle N operations at once") -- it does NOT solve DATA
CORRECTNESS problems (two writes to the same object racing each other).
That's a genuinely different problem, solved by DataMediator's
per-object lock in core/ontology/mediator.py. Conflating the two was a
real design mistake caught during review -- see that file's docstring
for the corrected reasoning.
"""

import threading
from contextlib import contextmanager


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int | None):
        self._semaphore = threading.Semaphore(max_concurrent) if max_concurrent is not None else None

    @contextmanager
    def limit(self):
        if self._semaphore is None:
            yield
        else:
            with self._semaphore:
                yield


class KeyedLockManager:
    """One lock per key, from a BOUNDED, pre-allocated set.

    Keys are striped onto a fixed number of locks, so memory is
    constant no matter how many distinct objects a deployment ever
    touches.

    THIS REPLACED AN UNBOUNDED LEAK. The previous version created a
    lock per key with dict.setdefault() and never evicted one --
    measured at ~164 bytes retained per distinct object ever written,
    which is 6 GB after a year at 100k writes/day and 60 GB at 1M/day.
    A long-running deployment would eventually be killed by the OOM
    reaper. It was documented as "a known, deliberate tradeoff -- fine
    for this project's scope", which was true of a prototype and not
    of a product.

    STRIPING RATHER THAN REFERENCE-COUNTED EVICTION, deliberately.
    Both are standard answers to this and both are correct. Eviction
    keeps memory proportional to keys currently CONTENDED and never
    falsely blocks unrelated objects -- but it needs a lifecycle: a
    lock must not be removed while a thread is waiting on it, which is
    its own race to get wrong, in the code whose entire job is getting
    races right.

    Striping has no lifecycle at all. Nothing is created, nothing is
    removed, and the manager cannot be wrong about when. Its cost is
    FALSE CONTENTION: two unrelated objects can share a stripe and
    block each other needlessly. With 1024 stripes and a write path
    bounded by a small thread pool, that is rare and merely slow --
    where the failure it replaces was unbounded and fatal.

    The safety asymmetry decides it. A shared stripe blocking too much
    is a performance bug; a lock failing to exclude is a correctness
    one.
    """

    # A power of two so the mask below is an exact modulo. 1024 locks
    # is ~164 KB, fixed, and matches the stripe counts used by
    # established striped-lock implementations.
    STRIPES = 1024

    def __init__(self):
        # Allocated up front: there is no creation path, so there is
        # no check-then-act to get wrong.
        self._locks: list[threading.Lock] = [threading.Lock() for _ in range(self.STRIPES)]

    def lock_for(self, key) -> threading.Lock:
        # hash() is stable within a process, which is all that is
        # needed -- the mapping never has to survive a restart, since
        # locks protect only in-flight work.
        return self._locks[hash(key) & (self.STRIPES - 1)]
