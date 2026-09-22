"""
concurrency_limited_adapter.py  (generic -- wraps ANY LLMAdapter)

Enforces max_concurrent_requests from the OUTSIDE -- concrete adapters
(adapters/ollama_adapter.py) never implement their own throttling;
build_llm_adapter() in core/deployment_loader.py always wraps whatever
it constructs in this, so callers never need to know it exists.
"""

from core.concurrency import ConcurrencyLimiter
from core.llm.interface import LLMAdapter, TokenUsage


class ConcurrencyLimitedLLMAdapter:
    def __init__(self, wrapped: LLMAdapter):
        self._wrapped = wrapped
        # NAMED BY THE SERVER, not the model: the cap is the server's.
        # The step and synthesis models usually share one Ollama, and
        # each wrapper used to hold its own semaphore -- two requests at
        # once to a server capped at 1, even in a single worker.
        server = getattr(wrapped, "base_url", None) or getattr(wrapped, "executable", "")
        self._limiter = ConcurrencyLimiter(
            wrapped.max_concurrent_requests,
            name=f"llm/{type(wrapped).__name__}/{server}",
        )
        # Re-exposed, not just consumed internally -- this class is
        # itself typed (and used) as an LLMAdapter, which DECLARES
        # max_concurrent_requests as a required attribute (see
        # interface.py's own Protocol). Without this, any code that
        # ever needed to introspect a wrapped adapter's own
        # concurrency characteristic (or wrapped one of these in
        # ANOTHER layer) would hit a real AttributeError -- caught by
        # mypy checking this class against the Protocol it claims to
        # satisfy, not by any runtime path exercising it yet.
        self.max_concurrent_requests = wrapped.max_concurrent_requests

    # THE REAL SIGNATURE, not *args/**kwargs (001's F-04): that erased
    # the Protocol's types at the one layer every call passes through, and
    # a keyword misspelled here -- `deadlin=` -- would have reached the
    # adapter unchecked.
    def chat(self, system_prompt: str, user_message: str,
              json_mode: bool = False, temperature: float | None = None, *,
              deadline: float | None = None, usage: TokenUsage | None = None) -> str:
        with self._limiter.limit():
            return self._wrapped.chat(system_prompt, user_message, json_mode, temperature,
                                      deadline=deadline, usage=usage)
