"""
concurrency_limited_adapter.py  (generic -- wraps ANY LLMAdapter)

Enforces max_concurrent_requests from the OUTSIDE -- concrete adapters
(adapters/ollama_adapter.py) never implement their own throttling;
build_llm_adapter() in core/deployment_loader.py always wraps whatever
it constructs in this, so callers never need to know it exists.
"""

from core.concurrency import ConcurrencyLimiter
from core.llm.interface import LLMAdapter


class ConcurrencyLimitedLLMAdapter:
    def __init__(self, wrapped: LLMAdapter):
        self._wrapped = wrapped
        self._limiter = ConcurrencyLimiter(wrapped.max_concurrent_requests)
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

    def chat(self, *args, **kwargs) -> str:
        with self._limiter.limit():
            return self._wrapped.chat(*args, **kwargs)
