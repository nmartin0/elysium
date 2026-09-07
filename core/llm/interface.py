"""
interface.py  (the LLM contract -- generic, zero implementation knowledge)

One method, deliberately narrow -- see chat()'s own reasoning below.
max_concurrent_requests is a REQUIRED declaration (like DataSiloAdapter's
concurrency fields) -- core/llm/concurrency_limited_adapter.py enforces
it, adapters don't self-protect.
"""

from typing import Protocol


class LLMUnavailable(Exception):
    """The backend could not be reached, or did not answer.

    Raised by ADAPTERS, so the agent loop can tell "the model was
    unreachable" apart from "the model answered with something
    unparseable". Those look identical from a caught exception and are
    completely different events: the second means do the best you can
    with what you have, the first means you have nothing and must say
    so.

    A shared type rather than each adapter's own, because the loop
    previously caught requests.RequestException -- one adapter's
    transport library. A second adapter raising anything else went
    entirely unhandled.
    """


class LLMAdapter(Protocol):
    max_concurrent_requests: int | None

    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None) -> str:
        # Sends one message, returns raw response text, raises on
        # failure. No JSON parsing, no step validation -- callers
        # (agent_step_prompt.py, synthesis_prompt.py) differ too much
        # in what they need from a response for this to live here.
        ...
