"""
ollama_adapter.py  (Ollama-specific -- the only place Ollama's API shape exists)

Implements core/llm/interface.py's LLMAdapter contract. Constructed from
(model, connection: dict) -- connection comes straight from this
deployment's config.yaml llm.connection block (e.g. {"base_url": ...,
"request_timeout_seconds": ...}), opaque to core/, meaningful only here
-- same pattern as adapters/sqlite_adapter.py's SQLiteAdapter.

Used by: core/deployment_loader.py's build_llm_adapter() factory
"""

from typing import Any

import requests

from core.llm.interface import LLMUnavailable


class OllamaAdapter:
    def __init__(self, model: str, connection: dict):
        self.model = model
        self.base_url = connection["base_url"]
        self.timeout_seconds = connection.get("request_timeout_seconds", 180)
        # Real capacity limit on THIS hardware -- one local model, one
        # inference at a time. A hosted API adapter would declare a
        # much higher number, or None.
        self.max_concurrent_requests = connection.get("max_concurrent_requests", 1)
        # PROVIDER OPTIONS, passed through opaquely. Anything Ollama
        # accepts under its own "options" key -- num_ctx, num_thread,
        # num_batch, seed, and so on -- is a deployment decision, not a
        # code change: different hardware genuinely needs different
        # values, and enumerating Ollama's option names in core/ would
        # both break llm_connection's deliberate opacity and go stale.
        #
        # NAMESPACED UNDER "options", NEVER MERGED INTO THE PAYLOAD.
        # This is a security property, not a style choice. Ollama's
        # "messages" and "format" are TOP-LEVEL keys; a blind
        # payload.update(config) would let a config file rewrite the
        # conversation itself or silently disable JSON mode. Config
        # supplies inference parameters and nothing else.
        #
        # The cost of opacity, stated plainly: a misspelled option name
        # is ignored by Ollama at request time rather than rejected at
        # load, which is weaker than this project's usual "fail loudly
        # at startup" discipline. Accepted because validating the names
        # here would require core/ to carry Ollama's option list.
        self.options = dict(connection.get("options") or {})
        # Whether the model stays resident between requests. Ollama's
        # own default evicts after five minutes; -1 pins it. On CPU-only
        # hardware a reload has been measured at 12-47 seconds, paid
        # once per query or worse, so this is worth a deployment being
        # able to set.
        self.keep_alive = connection.get("keep_alive")

    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None) -> str:
        # Raises requests.RequestException on network/timeout failure --
        # callers decide what "failure" should mean for them (e.g. the
        # agent loop fails closed to "finish"; synthesis returns an
        # error string), so this method doesn't swallow the exception.
        #
        # Explicitly dict[str, Any] -- without this, mypy infers a
        # narrower type from the literal dict below (a mix of str,
        # list[dict[str, str]], and bool), then the two conditional
        # assignments further down (adding a str, then a dict[str,
        # float]) don't structurally fit that inferred type either,
        # surfacing as an incompatibility against requests.post()'s
        # own json parameter stub (JsonType) -- a real, environment-
        # dependent finding: only visible with types-requests actually
        # installed, which is why this went unnoticed until checked
        # against an environment that had it.
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        # THE CALLER'S TEMPERATURE WINS over a configured one,
        # deliberately. next_step() passes temperature=0 because a step
        # has to parse as one specific JSON shape; a deployment quietly
        # raising it would make step selection erratic and the audit
        # trail harder to reason about. Config sets a default for calls
        # that express no opinion, never an override for those that do.
        options = {**self.options}
        if temperature is not None:
            options["temperature"] = temperature
        if options:
            payload["options"] = options

        try:
            response = requests.post(self.base_url, json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as e:
            # Translated at the boundary so callers never need to know
            # this adapter uses `requests` -- see LLMUnavailable.
            raise LLMUnavailable(f"Could not reach the model at {self.base_url}: {e}") from e
        response.raise_for_status()
        return response.json()["message"]["content"]
