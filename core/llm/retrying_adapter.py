"""One transient failure should not end a whole query (AL-5).

A query makes one model call per hop and another to synthesise. A
single refused connection anywhere in that chain ended the run and the
user got nothing -- having already paid for every hop before it. The
work is not idempotent to redo: the hops already taken cost real
prefill, and they are lost with the query.

WHAT IS RETRIED IS NARROW, and deliberately so. Only
LLMUnavailable.retryable, which the adapters set on transport failures
alone. A deadline that has already passed, an unparseable response and
a 4xx are all NOT retried -- see LLMUnavailable's own reasoning for
why each. At temperature 0 a retried prompt returns the same bytes, so
retrying a bad ANSWER is a slower way to fail.

THE DEADLINE IS WHAT ACTUALLY BOUNDS THIS, not the attempt count.
call_timeout() raises the moment `deadline` has passed, before
anything is sent, and that exception is not retryable -- so a retry
loop cannot outlive the query's budget no matter how many attempts it
is configured for. The count bounds a backend that is failing fast;
the deadline bounds everything else. Both are needed: without the
count, a backend refusing instantly would spin until the deadline.

BACKOFF IS SLEPT OUTSIDE THE CONCURRENCY LIMIT, which is why this
wraps ConcurrencyLimitedLLMAdapter rather than the other way round:

    Retrying(ConcurrencyLimited(concrete))   <- correct
    ConcurrencyLimited(Retrying(concrete))   <- holds a slot while
                                               sleeping

The step and synthesis models usually share one Ollama capped at a
small number of concurrent requests. Sleeping through a backoff while
holding one of those slots would make a struggling backend starve the
requests that are still healthy -- turning a transient failure for one
user into a queue for everyone.
"""

import logging
import time

from core.llm.interface import LLMAdapter, LLMUnavailable, TokenUsage

logger = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF_SECONDS = 0.5


class RetryingLLMAdapter:
    def __init__(self, wrapped: LLMAdapter, attempts: int = DEFAULT_ATTEMPTS,
                 backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
                 sleep=time.sleep):
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self._wrapped = wrapped
        self._attempts = attempts
        self._backoff_seconds = backoff_seconds
        # INJECTED so a test can force the interleaving rather than
        # race it, and so the suite does not actually sleep.
        self._sleep = sleep
        # Re-exposed for the same reason the concurrency wrapper does
        # it: this class is itself used as an LLMAdapter, and the
        # Protocol declares the attribute.
        self.max_concurrent_requests = wrapped.max_concurrent_requests

    # THE REAL SIGNATURE, not *args/**kwargs (F-04): that erased the
    # Protocol's types at a layer every call passes through, and a
    # keyword misspelled here would reach the adapter unchecked.
    def chat(self, system_prompt: str, user_message: str,
             json_mode: bool = False, temperature: float | None = None, *,
             deadline: float | None = None, usage: TokenUsage | None = None) -> str:
        for attempt in range(1, self._attempts + 1):
            try:
                return self._wrapped.chat(system_prompt, user_message, json_mode,
                                          temperature, deadline=deadline, usage=usage)
            except LLMUnavailable as e:
                last = attempt == self._attempts
                if not e.retryable or last:
                    # RE-RAISED UNCHANGED, carrying the real cause. A
                    # wrapper that replaced this with "failed after 3
                    # attempts" would hide which of four very different
                    # failures happened, and three of them are not even
                    # retried.
                    raise
                logger.warning(
                    f"model call failed ({e}); retrying "
                    f"{attempt + 1}/{self._attempts} in {self._backoff_seconds}s"
                )
                self._sleep(self._backoff_seconds)
        # Unreachable: the final attempt either returns or re-raises
        # above. Here so that a future edit to the loop cannot make the
        # function fall off the end returning None, which a caller
        # would treat as an answer.
        raise AssertionError("retry loop completed without returning or raising")
