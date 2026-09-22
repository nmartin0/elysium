"""
chat() honours a request's deadline and reports what the provider
counted (E-11, the adapter contract; the query wiring is the next
commit).

BEFORE: each call had only its own timeout -- 180 s by default -- with
nothing bounding a query's many calls; and chat() returned bare text,
dropping every token count the provider sent back.

The deadline is tested with a STALLED transport: one that waits exactly
as long as it is allowed to, then fails as a real timeout does.
"""

import inspect
import os
import subprocess
import threading
import time

import pytest

import adapters.claude_agent_sdk_adapter as claude_module
import adapters.ollama_adapter as ollama_module
from adapters.claude_agent_sdk_adapter import ClaudeAgentSDKAdapter
from adapters.ollama_adapter import OllamaAdapter
from core.llm.concurrency_limited_adapter import ConcurrencyLimitedLLMAdapter
from core.llm.interface import LLMAdapter, LLMUnavailable, TokenUsage, call_timeout


class TestCallTimeout:
    def test_with_no_deadline_the_adapters_own(self):
        assert call_timeout(None, 180) == 180

    def test_a_far_deadline_leaves_it_alone(self):
        assert call_timeout(time.monotonic() + 3600, 180) == 180

    def test_a_near_deadline_shortens_it(self):
        assert 0 < call_timeout(time.monotonic() + 2, 180) <= 2

    def test_a_passed_deadline_refuses_before_sending(self):
        with pytest.raises(LLMUnavailable, match="deadline passed"):
            call_timeout(time.monotonic() - 1, 180)


class TestTokenUsage:
    def test_sums_what_was_reported(self):
        usage = TokenUsage()
        usage.add(10, 3)
        usage.add(5, 2)
        assert (usage.input_tokens, usage.output_tokens, usage.calls) == (15, 5, 2)

    def test_not_told_is_not_zero(self):
        usage = TokenUsage()
        usage.add(None, None)
        assert (usage.calls, usage.unreported, usage.input_tokens) == (1, 1, 0)

    def test_many_threads_lose_nothing(self):
        usage = TokenUsage()
        threads = [threading.Thread(target=lambda: [usage.add(1, 1) for _ in range(500)]) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert (usage.calls, usage.input_tokens) == (4000, 4000)


class StalledOllama:
    """requests.post stand-in: waits as long as it may, then times out."""

    def __init__(self):
        self.timeouts = []

    def __call__(self, url, json=None, timeout=None):
        self.timeouts.append(timeout)
        # Capped, so a regression to the adapter's own 180 s fails in
        # seconds; the RECORDED timeout is what proves the bound.
        time.sleep(min(timeout, 3))
        raise ollama_module.requests.Timeout("read timed out")


class Answering:
    def __init__(self, body):
        self.body = body

    def __call__(self, url, json=None, timeout=None):
        body = self.body

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return body
        return Response()


def _ollama():
    return OllamaAdapter("test-model", {"base_url": "http://ollama.invalid/api/chat"})


class TestOllama:
    def test_a_stalled_model_is_cut_off_at_the_deadline_not_its_timeout(self, monkeypatch):
        stalled = StalledOllama()
        monkeypatch.setattr(ollama_module.requests, "post", stalled)
        started = time.monotonic()

        with pytest.raises(LLMUnavailable):
            _ollama().chat("s", "u", deadline=time.monotonic() + 0.3)

        assert stalled.timeouts[0] <= 0.3
        assert time.monotonic() - started < 2  # not the adapter's 180 s

    def test_a_passed_deadline_sends_nothing(self, monkeypatch):
        stalled = StalledOllama()
        monkeypatch.setattr(ollama_module.requests, "post", stalled)

        with pytest.raises(LLMUnavailable):
            _ollama().chat("s", "u", deadline=time.monotonic() - 1)

        assert stalled.timeouts == []

    def test_its_counts_are_reported(self, monkeypatch):
        monkeypatch.setattr(ollama_module.requests, "post", Answering(
            {"message": {"content": "hi"}, "prompt_eval_count": 42, "eval_count": 7}))
        usage = TokenUsage()

        assert _ollama().chat("s", "u", usage=usage) == "hi"
        assert (usage.input_tokens, usage.output_tokens, usage.unreported) == (42, 7, 0)

    def test_counts_it_did_not_send_are_unreported(self, monkeypatch):
        monkeypatch.setattr(ollama_module.requests, "post", Answering({"message": {"content": "hi"}}))
        usage = TokenUsage()

        _ollama().chat("s", "u", usage=usage)

        assert (usage.calls, usage.unreported) == (1, 1)


@pytest.fixture
def claude_on_path(tmp_path, monkeypatch):
    """The adapter refuses to construct without `claude` on PATH. These
    tests replace subprocess.run, so a stub that is never run suffices --
    as tests/unit/test_claude_agent_sdk_adapter.py does it."""
    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")


@pytest.mark.usefixtures("claude_on_path")
class TestClaude:
    def _run(self, stdout, record):
        def run(*args, timeout=None, **kwargs):
            record.append(timeout)
            return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")
        return run

    def test_its_wait_is_bounded_by_the_deadline(self, monkeypatch):
        seen = []
        monkeypatch.setattr(claude_module.subprocess, "run", self._run('{"result": "hi"}', seen))

        ClaudeAgentSDKAdapter("m", {}).chat("s", "u", deadline=time.monotonic() + 0.5)

        assert 0 < seen[0] <= 0.5

    def test_a_stalled_cli_is_unavailable(self, monkeypatch):
        def stalled(*args, timeout=None, **kwargs):
            raise subprocess.TimeoutExpired("claude", timeout)
        monkeypatch.setattr(claude_module.subprocess, "run", stalled)

        with pytest.raises(LLMUnavailable, match="did not respond"):
            ClaudeAgentSDKAdapter("m", {}).chat("s", "u", deadline=time.monotonic() + 0.5)

    def test_its_counts_are_reported(self, monkeypatch):
        envelope = '{"result": "hi", "usage": {"input_tokens": 30, "output_tokens": 4}}'
        monkeypatch.setattr(claude_module.subprocess, "run", self._run(envelope, []))
        usage = TokenUsage()

        ClaudeAgentSDKAdapter("m", {}).chat("s", "u", usage=usage)

        assert (usage.input_tokens, usage.output_tokens) == (30, 4)

    def test_an_envelope_without_usage_is_unreported(self, monkeypatch):
        monkeypatch.setattr(claude_module.subprocess, "run", self._run('{"result": "hi"}', []))
        usage = TokenUsage()

        ClaudeAgentSDKAdapter("m", {}).chat("s", "u", usage=usage)

        assert usage.unreported == 1


class TestTheLimiter:
    def test_has_the_protocols_signature(self):
        """001's F-04: *args/**kwargs erased it."""
        assert (inspect.signature(ConcurrencyLimitedLLMAdapter.chat).parameters.keys()
                == inspect.signature(LLMAdapter.chat).parameters.keys())

    def test_passes_the_deadline_and_usage_through(self, monkeypatch):
        seen = {}

        class Recording:
            max_concurrent_requests = 1

            def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
                     deadline=None, usage=None):
                seen.update(deadline=deadline, usage=usage)
                return "ok"
        usage, deadline = TokenUsage(), time.monotonic() + 5

        ConcurrencyLimitedLLMAdapter(Recording()).chat("s", "u", deadline=deadline, usage=usage)

        assert seen == {"deadline": deadline, "usage": usage}
