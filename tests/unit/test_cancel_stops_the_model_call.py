"""
A person who leaves stops the model call already running (AL-11).

Before: the cancel event was looked at between hops. The call in flight
ran to the end -- on a CPU deployment, minutes of the only model slot
spent on an answer nobody would read -- and the next question queued
behind it.

STOPPING OUR WAIT IS NOT THE POINT; STOPPING THE SERVER IS. Ollama
stops generating only when its request ends, so these tests use a real
HTTP server on localhost that records whether the client went away,
rather than a mock that could only say we stopped listening.
"""

import select
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from adapters import http_transport
from adapters.ollama_adapter import OllamaAdapter
from core.concurrency import ConcurrencyLimiter, WaitAbandoned
from core.llm.interface import LLMCancelled, LLMUnavailable

SLOW_SECONDS = 5.0


class _SlowModel(BaseHTTPRequestHandler):
    """Answers after SLOW_SECONDS, unless the client hangs up first --
    which it notices by watching its own socket, as a server does."""

    def do_POST(self):  # noqa: N802 - the http.server name
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        server = self.server
        ends = time.monotonic() + server.delay
        while time.monotonic() < ends:
            readable, _, _ = select.select([self.connection], [], [], 0.05)
            if readable and not self.connection.recv(1, 0x2):   # MSG_PEEK: b"" is a hang-up
                server.client_left.set()
                return
        body = b'{"message": {"content": "slow answer"}, "done": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def model_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowModel)
    server.delay = SLOW_SECONDS
    server.client_left = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


def _url(server):
    return f"http://127.0.0.1:{server.server_address[1]}/api/chat"


def _cancel_after(seconds):
    cancel = threading.Event()
    threading.Timer(seconds, cancel.set).start()
    return cancel


class TestTheTransport:
    def test_cancelling_closes_the_connection_and_the_server_sees_it(self, model_server):
        started = time.monotonic()

        with pytest.raises(LLMCancelled):
            http_transport.post(_url(model_server), json={}, timeout=30,
                                cancel=_cancel_after(0.3))

        assert time.monotonic() - started < 2.0, "the call was not abandoned"
        assert model_server.client_left.wait(2.0), "the server never saw the client go"

    def test_without_a_cancel_it_answers(self, model_server):
        """THE CONTROL: the tracking session is an ordinary one."""
        model_server.delay = 0.2

        response = http_transport.post(_url(model_server), json={}, timeout=30,
                                       cancel=threading.Event())

        assert response.json()["message"]["content"] == "slow answer"
        assert not model_server.client_left.is_set()

    def test_already_cancelled_sends_nothing(self, model_server):
        cancel = threading.Event()
        cancel.set()

        with pytest.raises(LLMCancelled):
            http_transport.post(_url(model_server), json={}, timeout=30, cancel=cancel)


class TestTheOllamaAdapter:
    def test_a_cancelled_chat_raises_cancelled_and_stops_the_server(self, model_server):
        adapter = OllamaAdapter("m", {"base_url": _url(model_server)})

        with pytest.raises(LLMCancelled):
            adapter.chat("system", "user", cancel=_cancel_after(0.3))

        assert model_server.client_left.wait(2.0)

    def test_cancelled_is_still_unavailable_to_old_handlers(self):
        """A subclass, so nothing written for "the model did not answer"
        can mistake a cancellation for an answer."""
        assert issubclass(LLMCancelled, LLMUnavailable)
        assert LLMCancelled("x").retryable is False


class TestWaitingForASlot:
    def test_a_waiter_gives_up_when_cancelled(self):
        limiter = ConcurrencyLimiter(1)
        held, release = threading.Event(), threading.Event()

        def hold():
            with limiter.limit():
                held.set()
                release.wait(5)

        threading.Thread(target=hold, daemon=True).start()
        held.wait(2)
        started = time.monotonic()
        try:
            with pytest.raises(WaitAbandoned):
                with limiter.limit(abandon=_cancel_after(0.2)):
                    pass
            assert time.monotonic() - started < 1.5
        finally:
            release.set()

    def test_a_waiter_not_cancelled_gets_the_slot(self):
        """THE CONTROL: abandon is not a timeout."""
        limiter = ConcurrencyLimiter(1)
        release = threading.Event()
        holding = threading.Event()

        def hold():
            with limiter.limit():
                holding.set()
                release.wait(5)

        threading.Thread(target=hold, daemon=True).start()
        holding.wait(2)
        threading.Timer(0.3, release.set).start()

        with limiter.limit(abandon=threading.Event()):
            got_it = True

        assert got_it


class TestTheLoop:
    def test_a_cancelled_call_ends_the_run_as_cancelled(self, test_db_path, test_schema):
        from adapters.sqlite_adapter import SQLiteWriteAdapter
        from core.agent.agentic_loop import AgentLoop, StopReason
        from core.intermediate_layer.auth import UserRecord
        from core.ontology.mediator import DataMediator

        roles = {"r": {"allowed_actions": ["read:Author"]}}
        mediator = DataMediator(test_schema, {"test_silo": SQLiteWriteAdapter({"path": test_db_path})},
                                {name: spec["storage"]["silo"] for name, spec in test_schema.items()},
                                roles)

        class _Leaving:
            max_concurrent_requests = None

            def chat(self, *args, cancel=None, **kwargs):
                assert cancel is not None, "the loop did not pass its cancel event on"
                raise LLMCancelled("gone")

        result = AgentLoop(_Leaving(), mediator).run(
            UserRecord("alice", "org-a", "r"), "q", threading.Event())

        assert result.stop_reason is StopReason.CANCELLED


@pytest.mark.skipif(sys.platform == "win32", reason="uses a POSIX sleep command")
def test_the_claude_cli_is_killed_when_cancelled(tmp_path):
    """The process IS the request for this adapter, so ending it is what
    stops the work."""
    from adapters.claude_agent_sdk_adapter import ClaudeAgentSDKAdapter

    adapter = ClaudeAgentSDKAdapter.__new__(ClaudeAgentSDKAdapter)
    adapter._environment = lambda: None
    started = time.monotonic()

    with pytest.raises(LLMCancelled):
        adapter._run_until_cancelled([sys.executable, "-c", "import time; time.sleep(30)"],
                                     "", 60, _cancel_after(0.3))

    assert time.monotonic() - started < 3.0
