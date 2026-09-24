"""
Talking to vLLM, and letting the engine set the concurrency (INFER-1).

WHY IT EXISTS: at one request vLLM and Ollama are within about 20%,
and Ollama is often faster on first-response latency. Past four to
eight concurrent requests vLLM leads by two to nine times, and at
saturation Red Hat measured 793 output tokens a second against
Ollama's 41 (SCALABILITY.md). So it is a per-deployment CHOICE --
Ollama for a laptop or a small team, vLLM where concurrency is real --
which is what the adapter interface is for.

EVERY FAILURE IS TRANSLATED AT THE BOUNDARY, as F-22 forced the Ollama
adapter to do. A caller that handles LLMUnavailable should never meet
requests.HTTPError: that is a fact about the library this adapter
happens to use.
"""

import pytest
import requests

from adapters.vllm_adapter import DEFAULT_MAX_CONCURRENT_REQUESTS, VLLMAdapter
from core.deployment_loader import _default_concurrency
from core.llm.interface import LLMUnavailable, TokenUsage

CONNECTION = {"base_url": "http://gpu:8000/v1/chat/completions"}


class _Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


@pytest.fixture
def answering(monkeypatch):
    def install(response, capture=None):
        def post(url, json=None, headers=None, timeout=None):
            if capture is not None:
                capture.update({"url": url, "payload": json, "headers": headers,
                                 "timeout": timeout})
            return response
        monkeypatch.setattr(requests, "post", post)
        return VLLMAdapter("mistral", CONNECTION)
    return install


def _answer(content="hello", **extra):
    return _Response(200, {"choices": [{"message": {"content": content}}], **extra})


class TestAGoodAnswer:
    def test_the_content_comes_back(self, answering):
        assert answering(_answer()).chat("system", "user") == "hello"

    def test_tokens_are_counted_in_openais_names(self, answering):
        """prompt_tokens in, completion_tokens out -- vLLM reports
        OpenAI's names, not Ollama's."""
        response = _answer(usage={"prompt_tokens": 12, "completion_tokens": 3})
        usage = TokenUsage()

        answering(response).chat("system", "user", usage=usage)

        assert usage.input_tokens == 12 and usage.output_tokens == 3

    def test_a_missing_usage_block_is_not_a_crash(self, answering):
        """Absent on some error shapes, which is why it is read
        defensively rather than indexed."""
        usage = TokenUsage()

        answering(_answer()).chat("system", "user", usage=usage)

        assert usage.input_tokens == 0

    def test_json_mode_is_asked_for_in_openais_dialect(self, answering):
        captured: dict = {}

        answering(_answer(), captured).chat("system", "user", json_mode=True)

        assert captured["payload"]["response_format"] == {"type": "json_object"}

    def test_the_prompts_are_sent_as_two_messages(self, answering):
        captured: dict = {}

        answering(_answer(), captured).chat("a system prompt", "a question")

        roles = [message["role"] for message in captured["payload"]["messages"]]
        assert roles == ["system", "user"]

    def test_an_api_key_becomes_a_bearer_header(self, monkeypatch):
        captured: dict = {}

        def post(url, json=None, headers=None, timeout=None):
            captured.update({"headers": headers})
            return _answer()
        monkeypatch.setattr(requests, "post", post)

        VLLMAdapter("m", {**CONNECTION, "api_key": "secret"}).chat("system", "user")

        assert captured["headers"]["Authorization"] == "Bearer secret"


class TestEveryFailureIsTranslated:
    @pytest.mark.parametrize("response, expected", [
        (_Response(503, {}), "answered 503"),
        (_Response(200, {"object": "error", "message": "model not found"}), "model not found"),
        (_Response(200, {"choices": []}), "without a message"),
        (_Response(200, ValueError("Expecting value")), "not JSON"),
    ])
    def test_it_becomes_LLMUnavailable(self, answering, response, expected):
        with pytest.raises(LLMUnavailable, match=expected):
            answering(response).chat("system", "user")

    def test_a_network_failure_too(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise requests.ConnectionError("connection refused")
        monkeypatch.setattr(requests, "post", refuse)

        with pytest.raises(LLMUnavailable, match="Could not reach"):
            VLLMAdapter("m", CONNECTION).chat("system", "user")


class TestTheConcurrencyFollowsTheEngine:
    """THE OLD DEFAULT WAS FOUR FOR EVERYONE, which matched Ollama's own
    parallel cap BY COINCIDENCE -- so a deployment that swapped to vLLM
    and changed nothing else would have seen no improvement, with no
    reason to suspect the limit was ours rather than the engine's."""

    def test_ollama_keeps_four(self):
        config = {"agent": {}, "llm": {"provider": "ollama"}}

        assert _default_concurrency(config) == 4

    def test_vllm_gets_more(self):
        config = {"agent": {}, "llm": {"provider": "vllm"}}

        assert _default_concurrency(config) == 16

    def test_a_declared_number_always_wins(self):
        """A deployment that states a number has a reason."""
        assert _default_concurrency(
            {"agent": {"max_concurrent_requests": 2}, "llm": {"provider": "vllm"}}) == 2
        assert _default_concurrency(
            {"agent": {"max_concurrent_requests": 32}, "llm": {"provider": "ollama"}}) == 32

    def test_the_adapters_own_default_is_its_own_business(self):
        """The server's pool and the adapter's limit are different
        numbers: one bounds this process, the other protects a backend
        that can only do one thing at a time."""
        assert VLLMAdapter("m", CONNECTION).max_concurrent_requests == \
            DEFAULT_MAX_CONCURRENT_REQUESTS


class TestItIsRegistered:
    def test_a_deployment_can_ask_for_vllm(self):
        from core.deployment_loader import _LLM_ADAPTER_REGISTRY

        assert _LLM_ADAPTER_REGISTRY["vllm"] is VLLMAdapter
