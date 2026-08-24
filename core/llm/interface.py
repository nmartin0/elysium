"""
interface.py  (the LLM contract -- generic, zero implementation knowledge)

LLMAdapter is what EVERY concrete LLM backend adapter (adapters/ollama_adapter.py,
and any future one -- LM Studio, llama.cpp, a hosted API) must implement.
One method, deliberately narrow: it sends messages, returns raw response
text, and raises on failure. It does NOT know about JSON parsing, step
validation, or fallback behavior -- those differ meaningfully between
callers (core/llm/agent_step_prompt.py wants structured JSON with
temperature=0; core/llm/synthesis_prompt.py wants plain prose with no
format constraint), so that logic correctly stays in each caller, not
pushed down here.
"""

from typing import Protocol


class LLMAdapter(Protocol):
    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None) -> str:
        ...
