"""
interface.py  (the LLM contract -- generic, zero implementation knowledge)

One method, deliberately narrow -- see chat()'s own reasoning below.
max_concurrent_requests is a REQUIRED declaration (like DataSiloAdapter's
concurrency fields) -- core/llm/concurrency_limited_adapter.py enforces
it, adapters don't self-protect.
"""

import threading
import time
from dataclasses import dataclass, field
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


@dataclass
class TokenUsage:
    """What the provider REPORTED it consumed, summed over calls (E-11).

    chat() returns only text, so the counts every provider sends back
    were dropped. A caller that wants them passes one of these, and each
    adapter adds what its provider reported. `unreported` counts calls
    whose provider reported nothing -- so "no tokens" is never mistaken
    for "not told".

    Thread-safe: one query's calls may run on more than one thread.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    unreported: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, input_tokens: int | None, output_tokens: int | None) -> None:
        with self._lock:
            self.calls += 1
            if input_tokens is None and output_tokens is None:
                self.unreported += 1
                return
            self.input_tokens += input_tokens or 0
            self.output_tokens += output_tokens or 0


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
