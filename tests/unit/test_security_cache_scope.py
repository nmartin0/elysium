"""
How the security cache is scoped -- see core/ontology/mediator._SECURITY_CACHE.

004-F6 WAS A MAC BYPASS because the cache was an attribute of the one
mediator every user shares, cleared only by somebody's next prefetch.
These pin the mechanism that replaced it.
"""

import inspect

import pytest

import core.ontology.mediator as mediator_module
from core.ontology.mediator import _SECURITY_CACHE, security_cache_scope


class TestTheScope:
    def test_there_is_no_cache_outside_one(self):
        """NO SCOPE, NO CACHE -- so a forgotten scope is slower, never
        stale."""
        assert _SECURITY_CACHE.get() is None

    def test_a_scope_provides_one_and_removes_it(self):
        with security_cache_scope():
            assert _SECURITY_CACHE.get() is not None
        assert _SECURITY_CACHE.get() is None

    def test_a_nested_scope_reuses_the_outer(self):
        """HOW A PAGE SHARES: a search then its get_object calls, each
        opening a scope, all land in the request's."""
        with security_cache_scope():
            outer = _SECURITY_CACHE.get()
            with security_cache_scope():
                assert _SECURITY_CACHE.get() is outer
            assert _SECURITY_CACHE.get() is outer

    def test_it_is_removed_even_when_the_call_raises(self):
        """ALWAYS RESET: executor threads keep their context between
        tasks, so a cache left behind would bring the bug back one thread
        at a time."""
        with pytest.raises(RuntimeError), security_cache_scope():
            raise RuntimeError("the call failed")
        assert _SECURITY_CACHE.get() is None

    def test_two_scopes_in_turn_do_not_share(self):
        with security_cache_scope():
            first = _SECURITY_CACHE.get()
        with security_cache_scope():
            second = _SECURITY_CACHE.get()
        assert first is not second


class TestTheMediatorHoldsNone:
    def test_no_instance_attribute_is_a_security_cache(self):
        """A SOURCE-LEVEL TRIPWIRE. A cache stored on the mediator is
        shared by every user and thread -- 004-F6 exactly -- and a
        behavioural test would only catch it if it happened to warm,
        change and read in that order."""
        source = inspect.getsource(mediator_module.DataMediator)
        assert "self._security_value_cache" not in source
        assert "self._security_link_cache" not in source

    def test_the_prefetch_stores_nothing_without_a_scope(self, monkeypatch):
        """A prefetch outside any scope must not create one: a stray
        cache in a thread's base context outlives the call."""
        from core.ontology.mediator import DataMediator
        mediator = DataMediator.__new__(DataMediator)
        mediator._prefetch_security_values("Customer", ["cust_001"])
        assert _SECURITY_CACHE.get() is None


class TestAnAgentQueryIsOneScope:
    def test_run_opens_a_scope_around_the_whole_query(self, monkeypatch):
        """THE LOOP RUNS ON AN EXECUTOR THREAD, which the per-request
        middleware's scope does not reach -- so run() opens its own, for
        all of a query's hops."""
        from core.agent.agentic_loop import AgentLoop
        seen = []
        monkeypatch.setattr(AgentLoop, "_run",
                            lambda self, *args: seen.append(_SECURITY_CACHE.get()) or "done")
        loop = AgentLoop.__new__(AgentLoop)

        assert loop.run("user", "question") == "done"
        assert seen and seen[0] is not None
        assert _SECURITY_CACHE.get() is None
