"""
Every LLM adapter a deployment builds retries, and retries OUTSIDE
the concurrency limiter (AL-R1).

REQUESTED BY THE AGENT-LOOP AGENT, who could not do it: the wiring
lives in core/deployment_loader.py, which is not their file, and the
adapter lived only on their branch, so this is the first commit where
the import even resolves.

WITHOUT THE WIRING THE WRAPPER WAS INERT. RetryingLLMAdapter was
built, tested by twelve tests of its own, and CONSTRUCTED BY NOTHING
-- so AL-5's retry behaviour did not exist in any running deployment.
A class with passing tests and no caller is the same shape as NEW-7
(a record nothing reads) and COORD-3 (a test nothing runs): green,
and not doing anything.

THE ORDER IS THE POINT, and their reasoning is right -- I checked it
before wiring. ConcurrencyLimitedLLMAdapter.chat holds

    with self._limiter.limit():

around the call. A retry nested INSIDE that would sleep while holding
a slot, turning one transient failure into a throughput collapse for
every other caller waiting on the cap. Outside, a sleeping retry
holds nothing and re-queues like any other request.

THE CAP MUST STILL BE VISIBLE THROUGH THE WRAPPER: whatever reads
`max_concurrent_requests` off the adapter reads it off the OUTERMOST
object, and a wrapper that did not re-expose it would silently
report the wrong number -- or none.
"""

from types import SimpleNamespace

import pytest

from core.deployment_loader import build_llm_adapter
from core.llm.concurrency_limited_adapter import ConcurrencyLimitedLLMAdapter
from core.llm.retrying_adapter import RetryingLLMAdapter


def _adapter(provider="ollama"):
    config = SimpleNamespace(llm_provider=provider,
                              llm_connection={"base_url": "http://example"})
    return build_llm_adapter(config, "a-model")


class TestWhatADeploymentGets:
    def test_the_outermost_wrapper_retries(self):
        """THE REGRESSION TEST. This returned a bare
        ConcurrencyLimitedLLMAdapter, so nothing ever retried."""
        assert isinstance(_adapter(), RetryingLLMAdapter)

    def test_the_limiter_is_inside_it(self):
        adapter = _adapter()

        assert isinstance(adapter._wrapped, ConcurrencyLimitedLLMAdapter)

    def test_not_the_other_way_round(self):
        """Retrying INSIDE the limiter would sleep holding a slot.
        Stated as its own test because both orders 'work' and only one
        is correct."""
        adapter = _adapter()

        assert not isinstance(adapter._wrapped, RetryingLLMAdapter)
        assert not isinstance(adapter, ConcurrencyLimitedLLMAdapter)

    def test_the_concurrency_cap_is_still_readable(self):
        """Whatever reads this reads it off the OUTERMOST object."""
        assert _adapter().max_concurrent_requests >= 1

    @pytest.mark.parametrize("provider", ["ollama", "vllm"])
    def test_every_provider_gets_the_same_treatment(self, provider):
        """One construction site, so no provider can be forgotten --
        which is the reason this function exists at all."""
        adapter = build_llm_adapter(
            SimpleNamespace(llm_provider=provider,
                             llm_connection={"base_url": "http://example"}),
            "a-model")

        assert isinstance(adapter, RetryingLLMAdapter)
        assert isinstance(adapter._wrapped, ConcurrencyLimitedLLMAdapter)


class TestAnUnknownProviderIsStillRefused:
    def test_it_names_what_is_registered(self):
        """The wrapping must not swallow the error that tells an
        operator they mistyped a provider."""
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            _adapter(provider="not-a-provider")
