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
from pathlib import Path

# WHERE CAPS ARE SHARED ACROSS PROCESSES, or None for this process only.
#
# A CAP IS A PHYSICAL CAPACITY -- "this backend can only physically handle
# N operations at once" -- and a physical capacity does not multiply
# because the application runs more workers. Per-process semaphores did
# exactly that: four workers gave an Ollama server capped at 1 four
# requests at once, and a SQLite silo capped at 1 four writers.
#
# DIVIDING THE CAP BY THE WORKER COUNT CANNOT FIX IT: every declared cap
# defaults to 1, and 1 divided among four workers is still at least 1
# each. So the cap is SHARED instead -- N slot files, a slot held by an
# flock -- following run_sync.py's lock, and for its reason: released
# automatically when the process dies, so a crash leaves nothing stale.
#
# ONE PROCESS-WIDE SETTING, made once by create_app() before anything is
# built, rather than a directory threaded through every constructor: it
# says WHERE a machine-wide resource is coordinated, not how the
# deployment behaves. Unset -- tests, scripts -- limits are per process,
# exactly as before.
_shared_under: Path | None = None

# NAMED CAPS SHARE ONE SEMAPHORE PER PROCESS. The step and synthesis
# models each wrapped their LLM adapter with its OWN semaphore, so one
# Ollama server capped at 1 took two requests at once even in a single
# worker. Keyed by the name, both wrappers now hold the same one.
_named: dict[str, threading.Semaphore] = {}
_named_lock = threading.Lock()


def share_limits_under(directory: Path | None) -> None:
    """Enforce named caps across every process using `directory`."""
    global _shared_under
    _shared_under = directory


def _semaphore_for(name: str, max_concurrent: int) -> threading.Semaphore:
    with _named_lock:
        return _named.setdefault(name, threading.Semaphore(max_concurrent))


@contextmanager
def _shared_slot(directory: Path, name: str, slots: int):
    """Holds one of `slots` cross-process slots for `name`.

    BLOCKING, like the semaphore it extends: a caller over the cap waits
    its turn rather than failing. It polls, with a short backoff, because
    flock has no "wait for ANY of these N" -- only per file.
    """
    import fcntl
    import hashlib
    import time

    # HASHED, because a name carries a URL and a URL is not a path.
    folder = directory / "limits" / hashlib.sha256(name.encode()).hexdigest()[:16]
    folder.mkdir(parents=True, exist_ok=True)
    pause = 0.01
    while True:
        for slot in range(slots):
            handle = open(folder / f"slot-{slot}.lock", "a")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                continue
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
                handle.close()
            return
        time.sleep(pause)
        pause = min(pause * 2, 0.2)


class ConcurrencyLimiter:
    def __init__(self, max_concurrent: int | None, name: str | None = None):
        """`name` identifies the RESOURCE the cap belongs to -- a model
        server, a silo, a tool. Limiters with the same name share their
        cap: within a process always, and across processes once
        share_limits_under() has been called. Unnamed, a limiter is
        per-instance, as it always was."""
        self._max = max_concurrent
        self._name = name
        if max_concurrent is None:
            self._semaphore = None
        elif name is not None:
            self._semaphore = _semaphore_for(name, max_concurrent)
        else:
            self._semaphore = threading.Semaphore(max_concurrent)

    @contextmanager
    def limit(self):
        if self._semaphore is None:
            yield
            return
        with self._semaphore:
            # READ AT USE, not construction: limiters are built inside a
            # generation, and the setting only has to be made before the
            # first request, not before every build.
            shared = _shared_under
            if shared is None or self._name is None or self._max is None:
                yield
                return
            with _shared_slot(shared, self._name, self._max):
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
