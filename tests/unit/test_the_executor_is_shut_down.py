"""
The request executor is shut down deliberately, not by accident.

SEC-09, raised by the security agent and INHERITED when that agent was
destroyed -- "the executor drained only incidentally". Verified rather
than taken on trust: `app.state.executor` was constructed and
`shutdown()` appeared nowhere in `api/`, and the application had no
lifespan handler at all.

IT DID DRAIN, WHICH IS WHY NOBODY NOTICED. `concurrent.futures`
registers an atexit hook and its worker threads are NOT daemons, so
in-flight work was joined at INTERPRETER EXIT by the standard library.
Measured: the hook is in `concurrent.futures.thread`, and nothing in
it sets `daemon=True`.

SO THE FINDING IS NOT "work is lost". It is that nothing in this
application asked for the draining, nothing could bound how long it
took, and a graceful shutdown that is not interpreter exit -- a
reload, a signal the server handles itself -- did not drain it at all.

`wait=True` keeps exactly the behaviour that was already happening and
makes it the application's own, which is the difference between a
property and a coincidence.
"""

from pathlib import Path

SOURCE = Path("api/app.py").read_text()


class TestItIsWiredIn:
    def test_the_app_has_a_lifespan(self):
        """THE REGRESSION TEST. There was none at all."""
        assert "lifespan=_lifespan" in SOURCE

    def test_the_lifespan_shuts_the_executor_down(self):
        body = SOURCE[SOURCE.index("async def _lifespan"):]
        body = body[:body.index("\n    app = FastAPI")]

        assert "executor.shutdown(wait=True)" in body

    def test_it_waits_rather_than_abandoning_work(self):
        """`wait=False` would return immediately and leave in-flight
        requests to the atexit hook again -- the thing being fixed."""
        assert "shutdown(wait=False)" not in SOURCE

    def test_it_shuts_down_AFTER_serving(self):
        """A lifespan that shut down before its `yield` would close the
        executor at startup, which is worse than not having one."""
        body = SOURCE[SOURCE.index("async def _lifespan"):]
        body = body[:body.index("\n    app = FastAPI")]
        # THE CALL, not the word: the docstring explains the shutdown
        # above the yield, so searching for "shutdown" finds the prose.
        code = body[body.index('"""', body.index('"""') + 3):]

        assert code.index("yield") < code.index("executor.shutdown(")

    def test_a_missing_executor_is_not_an_error(self):
        """Any app built without one -- a test harness, a future
        variant -- must still shut down cleanly."""
        body = SOURCE[SOURCE.index("async def _lifespan"):]
        body = body[:body.index("\n    app = FastAPI")]

        assert "getattr(_app.state, \"executor\", None)" in body
        assert "is not None" in body


class TestWhatTheStandardLibraryWasDoingForUs:
    def test_the_atexit_hook_is_real(self):
        """The finding said "incidentally", and this is the incident:
        the behaviour was correct and came from somewhere else."""
        import inspect

        import concurrent.futures.thread as thread_module

        source = inspect.getsource(thread_module)

        assert "_python_exit" in source

    def test_worker_threads_are_not_daemons(self):
        """Daemon threads would be killed at exit and work WOULD be
        lost. They are not, which is why this was never a data-loss
        bug and is a shutdown-control one."""
        import inspect

        import concurrent.futures.thread as thread_module

        assert "daemon=True" not in inspect.getsource(thread_module)
