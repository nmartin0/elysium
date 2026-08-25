"""
ollama_adapter.py  (Ollama-specific -- the only place Ollama's API shape exists)

Implements core/llm/interface.py's LLMAdapter contract. Constructed from
(model, connection: dict) -- connection comes straight from this
deployment's config.yaml llm.connection block (e.g. {"base_url": ...,
"request_timeout_seconds": ...}), opaque to core/, meaningful only here
-- same pattern as adapters/sqlite_adapter.py's SQLiteAdapter.

Used by: core/deployment_loader.py's build_llm_adapter() factory
"""

import requests


class OllamaAdapter:
    def __init__(self, model: str, connection: dict):
        self.model = model
        self.base_url = connection["base_url"]
        self.timeout_seconds = connection.get("request_timeout_seconds", 180)
        # Real capacity limit on THIS hardware -- one local model, one
        # inference at a time. A hosted API adapter would declare a
        # much higher number, or None.
        self.max_concurrent_requests = connection.get("max_concurrent_requests", 1)

    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None) -> str:
        # Raises requests.RequestException on network/timeout failure --
        # callers decide what "failure" should mean for them (e.g. the
        # agent loop fails closed to "finish"; synthesis returns an
        # error string), so this method doesn't swallow the exception.
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        if temperature is not None:
            payload["options"] = {"temperature": temperature}

        response = requests.post(self.base_url, json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()["message"]["content"]
