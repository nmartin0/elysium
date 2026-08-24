"""
ollama_client.py  (generic Ollama HTTP wrapper -- org-agnostic)

A small class holding the three things every call to Ollama needs --
model, base URL, timeout -- so agent_step_prompt.py and
synthesis_prompt.py don't each independently build a requests.post()
call with their own copy of the same error handling. This was genuine
duplication, not just similar-looking code: both files had near-
identical try/except blocks around the same HTTP call.

chat() is deliberately narrow: it sends messages, returns raw response
text, and raises on failure -- it does NOT know about JSON parsing,
step validation, or fallback behavior. Those differ meaningfully between
the two callers (agent_step_prompt.py wants structured JSON with
temperature=0; synthesis_prompt.py wants plain prose with no format
constraint and no tools), so that logic correctly stays in each caller,
not pushed down into this shared class.

Used by: core/llm/agent_step_prompt.py, core/llm/synthesis_prompt.py,
         and core/agent/agentic_loop.py (to build its own step-selection client
         inside AgentLoop.from_deployment())
"""

import requests


class OllamaClient:
    def __init__(self, model: str, base_url: str, timeout_seconds: int = 180):
        # These three stay fixed for the client's lifetime -- every
        # chat() call reuses them, rather than re-passing all three
        # on every single call site.
        self.model = model
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    @classmethod
    def for_synthesis(cls, deployment) -> "OllamaClient":
        # The standard way every caller should build the synthesis
        # client -- one authoritative place reading
        # deployment.synthesis_model, instead of every call site
        # separately copy-pasting the same three-argument construction.
        return cls(deployment.synthesis_model, deployment.ollama_url, deployment.request_timeout_seconds)

    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None) -> str:
        # Sends one message, returns the model's raw text response.
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
