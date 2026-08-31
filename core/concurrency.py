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
    """Lazily-created lock per key. Uses dict.setdefault(), which
    Python's own thread-safety docs confirm is atomic -- no hand-rolled
    guard lock needed for the "check if missing, insert if so" step.
    Known, deliberate tradeoff: locks accumulate for the process
    lifetime (one per distinct key ever locked), never evicted. Fine
    for this project's scope; a long-running server touching unbounded
    distinct objects would want a real eviction policy eventually."""

    def __init__(self):
        self._locks: dict = {}

    def lock_for(self, key) -> threading.Lock:
        return self._locks.setdefault(key, threading.Lock())


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# CONTEXT: this file's own code is UNCHANGED here -- both classes had
# ZERO test coverage anywhere in the project until tests/unit/test_
# concurrency.py closed that gap, found while building a dedicated,
# genuinely multi-threaded proof for DataMediator._locks_for_objects()
# (core/ontology/mediator.py, see that file's own AI-notes for the
# fuller history). That new file covers KeyedLockManager directly
# (genuine mutual exclusion under real thread contention, not just
# structural correctness) and ConcurrencyLimiter too (found to be
# equally uncovered, cheap to close in the same pass).
