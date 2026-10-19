"""Where a question's seconds go, call by call (19 October).

The deployment's own measurements are about 5.4 tokens a second reading
a prompt and 1.5 writing a reply, so "a call took 50 s" cannot say what
to make smaller. Each call now records its wall-clock time and, where the
provider says, its reading, writing and loading time and how much of the
prompt it reused; a caller names which part of the question a call is
for, and the query's log line says where the time went.
"""

import json
import os
import subprocess

import pytest
import requests

import adapters.claude_agent_sdk_adapter as claude_module
import adapters.ollama_adapter as ollama_module
from adapters.claude_agent_sdk_adapter import ClaudeAgentSDKAdapter
from adapters.ollama_adapter import OllamaAdapter
from adapters.vllm_adapter import VLLMAdapter
from core.request_context import CallRecord, TokenUsage


def _answering(body):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return body

    def post(url, json=None, headers=None, timeout=None):
        return Response()
    return post


class TestTheTally:
    def test_a_part_records_into_the_whole(self):
        usage = TokenUsage()
        usage.for_part("step").add(100, 20, seconds=15.0, reading_seconds=2.0, writing_seconds=13.0)
        usage.for_part("answer").add(300, 90, seconds=61.0, writing_seconds=56.0)

        assert (usage.calls, usage.input_tokens, usage.output_tokens) == (2, 400, 110)
        assert [record.part for record in usage.records] == ["step", "answer"]

    def test_totals_by_part_in_the_order_they_came(self):
        usage = TokenUsage()
        step = usage.for_part("step")
        step.add(100, 20, seconds=15.0, reading_seconds=2.0, writing_seconds=13.0)
        usage.for_part("answer").add(300, 90, seconds=61.0)
        step.add(110, 22, seconds=16.0, reading_seconds=2.5, writing_seconds=13.5)

        totals = usage.by_part()

        assert list(totals) == ["step", "answer"]
        assert totals["step"]["calls"] == 2 and totals["step"]["seconds"] == 31.0
        assert totals["step"]["writing_seconds"] == 26.5 and totals["step"]["output_tokens"] == 42
        # NOT TOLD IS NOT ZERO: the answer's provider gave no split.
        assert totals["answer"]["reading_seconds"] is None

    def test_said_in_a_line(self):
        usage = TokenUsage()
        usage.for_part("step").add(100, 30, seconds=24.0, reading_seconds=4.0, writing_seconds=20.0)
        usage.for_part("answer").add(300, 90, seconds=61.0)

        assert usage.describe() == ("step 1 call 24.0s (reading 4.0s, writing 20.0s for 30 tokens at "
                                    "1.5/s); answer 1 call 61.0s (90 tokens written)")

    def test_an_untimed_call_is_counted_and_not_recorded(self):
        """What existed before: add(in, out) with no seconds still counts."""
        usage = TokenUsage()
        usage.add(10, 3)

        assert usage.calls == 1 and usage.records == []
        assert usage.describe() == "no timed model calls"

    def test_a_view_of_a_view_records_into_the_whole(self):
        usage = TokenUsage()
        usage.for_part("step").for_part("answer").add(1, 1, seconds=1.0)

        assert usage.records == [CallRecord("answer", 1, 1, 1.0)]


class TestOllama:
    def test_reading_writing_loading_and_reuse_from_its_nanoseconds(self, monkeypatch):
        monkeypatch.setattr(ollama_module.requests, "post", _answering({
            "message": {"content": "hi"}, "prompt_eval_count": 1200, "eval_count": 30,
            "prompt_eval_cached_count": 1150, "prompt_eval_duration": 9_500_000_000,
            "eval_duration": 20_000_000_000, "load_duration": 100_000_000}))
        usage = TokenUsage()

        OllamaAdapter("m", {"base_url": "http://ollama.invalid/api/chat"}).chat("s", "u", usage=usage)

        (record,) = usage.records
        assert (record.reading_seconds, record.writing_seconds, record.loading_seconds) == (9.5, 20.0, 0.1)
        assert record.cached_input_tokens == 1150 and record.output_tokens == 30
        assert record.seconds >= 0

    def test_an_older_ollama_without_timings_is_timed_by_the_clock(self, monkeypatch):
        monkeypatch.setattr(ollama_module.requests, "post", _answering(
            {"message": {"content": "hi"}, "prompt_eval_count": 12, "eval_count": 3}))
        usage = TokenUsage()

        OllamaAdapter("m", {"base_url": "http://ollama.invalid/api/chat"}).chat("s", "u", usage=usage)

        (record,) = usage.records
        assert record.reading_seconds is None and record.writing_seconds is None


class TestOpenAIStyle:
    def test_llama_servers_own_timings(self, monkeypatch):
        monkeypatch.setattr(requests, "post", _answering({
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 25},
            "timings": {"prompt_n": 40, "prompt_ms": 7400.0, "predicted_n": 25,
                        "predicted_ms": 16600.0, "cache_n": 760}}))
        usage = TokenUsage()

        VLLMAdapter("m", {"base_url": "http://gpu:8000/v1/chat/completions"}).chat("s", "u", usage=usage)

        (record,) = usage.records
        assert (record.reading_seconds, record.writing_seconds) == (7.4, 16.6)
        assert record.cached_input_tokens == 760

    def test_openais_cached_tokens_when_there_are_no_timings(self, monkeypatch):
        monkeypatch.setattr(requests, "post", _answering({
            "choices": [{"message": {"content": "hi"}}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 25,
                      "prompt_tokens_details": {"cached_tokens": 512}}}))
        usage = TokenUsage()

        VLLMAdapter("m", {"base_url": "http://gpu:8000/v1/chat/completions"}).chat("s", "u", usage=usage)

        (record,) = usage.records
        assert record.cached_input_tokens == 512 and record.writing_seconds is None


@pytest.fixture
def claude_on_path(tmp_path, monkeypatch):
    stub = tmp_path / "claude"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")


@pytest.mark.usefixtures("claude_on_path")
def test_a_hosted_model_is_timed_by_the_clock(monkeypatch):
    def run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args, 0, stdout='{"result": "hi", "usage": {"input_tokens": 3, "output_tokens": 1}}',
            stderr="")
    monkeypatch.setattr(claude_module.subprocess, "run", run)
    usage = TokenUsage()

    ClaudeAgentSDKAdapter("m", {}).chat("s", "u", usage=usage)

    (record,) = usage.records
    assert record.output_tokens == 1 and record.writing_seconds is None


class _Recording:
    """A model double that records the part each call was made for."""

    max_concurrent_requests = None

    def __init__(self, replies):
        self.replies = list(replies)
        self.parts = []

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        self.parts.append(usage._part if usage is not None else None)
        if usage is not None:
            usage.add(1, 1, seconds=0.01)
        return self.replies.pop(0)


class TestEachCallSaysWhatItIsFor:
    def test_a_step_a_plan_and_an_answer(self):
        from core.llm.agent_step_prompt import next_plan, next_step
        from core.llm.synthesis_prompt import synthesize_insight

        schema = {"Customer": {"id_field": "customer_id", "fields": {"name": {"type": "data"}}}}
        usage = TokenUsage()
        plan = {"plan": [{"id": "a", "step": "search_object", "object_type": "Customer",
                          "filter": {"name": "Ada"}}]}
        client = _Recording(['{"step": "finish"}', json.dumps(plan), "An answer [R1]."])

        next_step(client, "q", schema, [], [], False, {}, usage=usage)
        next_plan(client, "q", schema, [], False, {}, usage=usage)
        synthesize_insight(client, "q", [{"object_type": "Customer", "object_id": "c1",
                                          "field": "name", "value": "Ada"}], usage=usage)

        assert client.parts == ["step", "plan", "answer"]
        assert [record.part for record in usage.records] == ["step", "plan", "answer"]
