"""
interface.py  (the LLM contract -- generic, zero implementation knowledge)

One method, deliberately narrow -- see chat()'s own reasoning below.
max_concurrent_requests is a REQUIRED declaration (like DataSiloAdapter's
concurrency fields) -- core/llm/concurrency_limited_adapter.py enforces
it, adapters don't self-protect.
"""

import time
from typing import Protocol

from core.request_context import TokenUsage


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


# TokenUsage lives in core/request_context.py -- the context carries one,
# and sits BELOW this layer -- and is imported here for adapters to use.

def call_timeout(deadline: float | None, configured: float) -> float:
    """How long ONE call may wait: its adapter's own timeout, or the time
    left before `deadline` (a time.monotonic() value), whichever is less.

    E-11: each call had only its own timeout -- 180 s by default -- and a
    query making many calls had nothing bounding the whole. A deadline
    ALREADY PASSED raises here, before anything is sent: a call started
    with no time left can only waste the backend's.
    """
    if deadline is None:
        return configured
    left = deadline - time.monotonic()
    if left <= 0:
        raise LLMUnavailable("The request's deadline passed before the model was called.")
    return min(configured, left)


class LLMAdapter(Protocol):
    max_concurrent_requests: int | None

    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None, *,
              deadline: float | None = None, usage: TokenUsage | None = None) -> str:
        # Sends one message, returns raw response text, raises on
        # failure. No JSON parsing, no step validation -- callers
        # (agent_step_prompt.py, synthesis_prompt.py) differ too much
        # in what they need from a response for this to live here.
        ...
