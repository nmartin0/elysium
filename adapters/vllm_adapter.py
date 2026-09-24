"""Talking to vLLM, for a deployment with concurrent users (INFER-1).

WHY THIS EXISTS, AND WHEN IT IS THE RIGHT CHOICE. The benchmarks in
SCALABILITY.md are unambiguous about the shape: at ONE request vLLM
and Ollama are within about 20%, and Ollama is often faster on
first-response latency because it has no scheduler queue. Past roughly
four to eight concurrent requests vLLM leads by two to nine times, and
at saturation Red Hat measured 793 output tokens a second against
Ollama's 41, with p99 latency of 80 ms against 673.

The mechanism explains where that applies: Ollama inherits llama.cpp's
server and CAPS PARALLEL REQUESTS, queuing the rest, while vLLM's
continuous batching inserts new requests into the in-flight batch
token by token and PagedAttention keeps the KV cache from fragmenting.
"That architectural difference -- not a difference in raw decode speed
-- is what produces the concurrency-scaling gap", and it is also why
the gap nearly vanishes at one user.

SO: Ollama for a laptop or a small team, vLLM where concurrency is
real and a GPU exists. It is a per-deployment choice rather than a
migration, which is the whole point of there being an adapter
interface at all.

THE API IS OPENAI'S, which vLLM serves at /v1/chat/completions. That
means this adapter also reaches anything else speaking that dialect --
llama.cpp's own server, LM Studio, TGI, a hosted endpoint -- though
only vLLM is what the measurements above describe.

EVERY FAILURE IS TRANSLATED AT THE BOUNDARY, exactly as F-22 forced
the Ollama adapter to do: an HTTP error, a body that is not JSON, and
a well-formed answer of the wrong shape all become LLMUnavailable. A
caller that handles LLMUnavailable should never meet requests.
HTTPError, because that is a fact about the library this file happens
to use.
"""

from typing import Any

import requests

from core.llm.interface import LLMUnavailable, TokenUsage, call_timeout

DEFAULT_TIMEOUT_SECONDS = 180

# WHAT vLLM IS FOR. Ollama's own default parallel cap is four, and
# Elysium's max_concurrent_requests defaults to the same number by
# coincidence -- so a deployment that swapped the engine and changed
# nothing else would see no difference at all, which is the trap
# SCALABILITY.md names. A vLLM deployment that says nothing gets a
# limit worth having.
DEFAULT_MAX_CONCURRENT_REQUESTS = 16


class VLLMAdapter:
    """An OpenAI-compatible chat endpoint, as vLLM serves it."""

    def __init__(self, model: str, connection: dict):
        self.model = model
        self.base_url = connection["base_url"]
        self.timeout_seconds = connection.get("request_timeout_seconds",
                                               DEFAULT_TIMEOUT_SECONDS)
        # CONTINUOUS BATCHING IS THE POINT, so the limit here is a
        # different kind of number from Ollama's: there it protects one
        # local model from being asked for two things at once, here it
        # simply bounds how much this process will have in flight.
        self.max_concurrent_requests = connection.get(
            "max_concurrent_requests", DEFAULT_MAX_CONCURRENT_REQUESTS)
        self.api_key = connection.get("api_key")

    def model_name(self) -> str:
        return self.model

    def chat(self, system_prompt: str, user_message: str,
             json_mode: bool = False, temperature: float | None = None, *,
             deadline: float | None = None, usage: TokenUsage | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            # OpenAI's name for it, which vLLM implements. Asked for
            # rather than assumed: a model that ignores it still
            # answers, and the caller already handles an answer it
            # cannot parse (F-15).
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        # NO LONGER THAN THE REQUEST HAS LEFT (E-11), the same rule the
        # Ollama adapter follows.
        timeout = call_timeout(deadline, self.timeout_seconds)
        try:
            response = requests.post(self.base_url, json=payload, headers=headers,
                                      timeout=timeout)
        except requests.RequestException as e:
            raise LLMUnavailable(f"Could not reach the model at {self.base_url}: {e}") from e

        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise LLMUnavailable(
                f"The model at {self.base_url} answered {response.status_code}: {e}"
            ) from e
        try:
            body = response.json()
        except ValueError as e:
            raise LLMUnavailable(
                f"The model at {self.base_url} answered with something that is not JSON: {e}"
            ) from e

        if usage is not None:
            # OpenAI's names, which vLLM reports: prompt_tokens in,
            # completion_tokens out. Absent on some error shapes, which
            # is why they are read defensively rather than indexed.
            reported = body.get("usage") or {}
            usage.add(reported.get("prompt_tokens"), reported.get("completion_tokens"))

        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            # A WELL-FORMED ANSWER OF THE WRONG SHAPE. vLLM returns
            # {"object": "error", ...} for a model it has not loaded,
            # and an empty `choices` for a request it declined -- both
            # of which used to read, upstream, like a bug in Elysium.
            detail = body.get("message") or body.get("error") or body
            raise LLMUnavailable(
                f"The model at {self.base_url} answered without a message: {detail!r}"
            ) from e
