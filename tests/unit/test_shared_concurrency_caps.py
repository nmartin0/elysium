"""
A capacity cap is shared by every worker, not multiplied by them.

A CAP IS A PHYSICAL CAPACITY -- "this backend can only physically handle
N operations at once" -- and per-process semaphores multiplied it: four
workers gave an Ollama server capped at 1 four requests at once.

DIVIDING BY THE WORKER COUNT COULD NOT FIX IT: every declared cap
defaults to 1. So the cap is shared: N slot files, held by flock,
released automatically if the holder dies.

AND ONE PROCESS WAS ALREADY WRONG. The step and synthesis models each
wrapped their adapter with their own semaphore, so one server capped at
1 took two requests at once. Named caps now share one semaphore.
"""

import subprocess
import sys
import threading
import uuid

import pytest

from core.concurrency import ConcurrencyLimiter, share_limits_under


@pytest.fixture
def shared(tmp_path):
    """ALWAYS RESET: the setting is process-wide, and a test that left it
    on would change every test after it."""
    share_limits_under(tmp_path)
    try:
        yield tmp_path
    finally:
        share_limits_under(None)


def _name():
    # UNIQUE PER TEST, because named semaphores live for the process.
    return f"test/{uuid.uuid4()}"


def _hold_in_another_process(directory, name, cap):
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys\n"
         "from pathlib import Path\n"
         "from core.concurrency import ConcurrencyLimiter, share_limits_under\n"
         f"share_limits_under(Path({str(directory)!r}))\n"
         f"with ConcurrencyLimiter({cap}, name={name!r}).limit():\n"
         "    print('held', flush=True)\n"
         "    sys.stdin.readline()\n"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    line = holder.stdout.readline().strip()
    assert line == "held", holder.stderr.read()[-500:]
    return holder


def _release(holder):
    holder.stdin.write("go\n")
    holder.stdin.flush()
    holder.wait(timeout=10)


def _waits(limiter):
    """Starts using `limiter` on a thread; True if it is still waiting
    after a second."""
    done = threading.Event()

    def use():
        with limiter.limit():
            done.set()
    worker = threading.Thread(target=use, daemon=True)
    worker.start()
    worker.join(timeout=1.0)
    return not done.is_set(), worker, done


class TestTheCapSpansProcesses:
    def test_a_slot_held_by_another_worker_makes_this_one_wait(self, shared):
        name = _name()
        holder = _hold_in_another_process(shared, name, 1)
        try:
            waiting, worker, done = _waits(ConcurrencyLimiter(1, name=name))
            assert waiting, "went straight through a cap another worker held"
        finally:
            _release(holder)

        worker.join(timeout=10)
        assert done.is_set()

    def test_a_cap_of_two_admits_two(self, shared):
        """NOT A MUTEX. One slot held elsewhere leaves one free here."""
        name = _name()
        holder = _hold_in_another_process(shared, name, 2)
        try:
            waiting, _, _ = _waits(ConcurrencyLimiter(2, name=name))
            assert not waiting
        finally:
            _release(holder)

    def test_a_worker_that_dies_frees_its_slot(self, shared):
        """RELEASED BY THE KERNEL when the holder dies -- a crashed worker
        must not hold a model server's only slot for ever."""
        name = _name()
        holder = _hold_in_another_process(shared, name, 1)
        holder.kill()
        holder.wait(timeout=10)

        waiting, _, _ = _waits(ConcurrencyLimiter(1, name=name))

        assert not waiting


class TestOneProcessWasAlreadyWrong:
    def test_two_limiters_for_one_server_share_its_cap(self):
        """THE STEP AND SYNTHESIS MODELS each had their own semaphore, so
        one server capped at 1 took two at once. No shared directory
        needed -- this was wrong in a single worker."""
        name = _name()
        step, synthesis = ConcurrencyLimiter(1, name=name), ConcurrencyLimiter(1, name=name)

        with step.limit():
            waiting, _, _ = _waits(synthesis)
            assert waiting

    def test_the_llm_wrapper_names_its_cap_by_server(self):
        from core.llm.concurrency_limited_adapter import ConcurrencyLimitedLLMAdapter

        class _Ollama:
            base_url = "http://localhost:11434"
            max_concurrent_requests = 1

        step, synthesis = ConcurrencyLimitedLLMAdapter(_Ollama()), ConcurrencyLimitedLLMAdapter(_Ollama())

        assert step._limiter._semaphore is synthesis._limiter._semaphore


class TestUnsharedIsAsBefore:
    def test_no_directory_means_no_files(self, tmp_path):
        """TESTS AND SCRIPTS never call share_limits_under(), and keep
        the per-process behaviour they always had."""
        with ConcurrencyLimiter(1, name=_name()).limit():
            pass

        assert not (tmp_path / "limits").exists()

    def test_an_unnamed_limiter_is_per_instance(self):
        one, two = ConcurrencyLimiter(1), ConcurrencyLimiter(1)

        with one.limit():
            waiting, _, _ = _waits(two)
            assert not waiting
