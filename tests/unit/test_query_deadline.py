"""
A query's deadline bounds its gathering, and its token counts are kept
(E-11, the wiring; the adapter contract was patch 327).

The owner's default: 300 s, "until we can test on better hardware".
The deadline bounds the GATHERING -- the loop's many model calls. The
one synthesis call after keeps its own timeout, so a query that spent
its time gathering still answers from what it has.
"""

import json
import time
from pathlib import Path

import pytest

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import load_deployment
from core.intermediate_layer.auth import UserRecord
from core.llm.interface import LLMUnavailable
from core.llm.synthesis_prompt import synthesize_insight
from core.request_context import RequestContext, TokenUsage

USER = UserRecord("dana", "us-west", "debug")
CONFIG_DIR = Path(__file__).resolve().parents[2] / "deployment" / "etc"


class NoSchemaMediator:
    def visible_schema(self, user, for_agent=False):
        return {}


class Stalled:
    """A model that never answers: it waits as long as it is allowed --
    to the deadline -- and then fails as a real adapter does."""

    max_concurrent_requests = 1

    def __init__(self):
        self.calls = 0

    def chat(self, *args, deadline=None, usage=None, **kwargs):
        self.calls += 1
        time.sleep(min(max(deadline - time.monotonic(), 0), 3) if deadline else 3)
        raise LLMUnavailable("read timed out")


class Finishing:
    max_concurrent_requests = 1

    def chat(self, *args, deadline=None, usage=None, **kwargs):
        if usage is not None:
            usage.add(100, 20)
        return json.dumps({"step": "finish"})


def _loop(client):
    return AgentLoop(client=client, mediator=NoSchemaMediator())


class TestTheContext:
    def test_carries_a_deadline_and_a_tally(self):
        context = RequestContext.new(deadline_seconds=300)
        assert 299 < context.deadline - time.monotonic() <= 300
        assert isinstance(context.token_usage, TokenUsage)

    def test_without_a_deadline_has_none(self):
        assert RequestContext.new().deadline is None

    def test_the_shipped_default_is_the_owners_300(self):
        assert load_deployment(CONFIG_DIR).query_deadline_seconds == 300


class TestTheLoop:
    def test_a_stalled_model_ends_the_query_at_its_deadline(self):
        started = time.monotonic()

        result = _loop(Stalled()).run(USER, "q", context=RequestContext.new(deadline_seconds=0.3))

        assert result.ran_out_of_time
        assert time.monotonic() - started < 2  # the deadline, not the stall

    def test_a_deadline_already_passed_calls_no_model(self):
        client = Stalled()

        result = _loop(client).run(USER, "q", context=RequestContext.new(deadline_seconds=-1))

        assert result.ran_out_of_time and client.calls == 0

    def test_an_outage_with_time_left_is_still_an_error(self):
        """NOT MISTAKEN FOR RUNNING OUT OF TIME: only a passed deadline
        is that ending."""
        class Down:
            max_concurrent_requests = 1

            def chat(self, *args, **kwargs):
                raise LLMUnavailable("connection refused")

        with pytest.raises(LLMUnavailable, match="refused"):
            _loop(Down()).run(USER, "q", context=RequestContext.new(deadline_seconds=300))

    def test_its_token_counts_are_kept(self):
        context = RequestContext.new(deadline_seconds=300)

        _loop(Finishing()).run(USER, "q", context=context)

        assert context.token_usage.calls >= 1
        assert context.token_usage.input_tokens == 100 * context.token_usage.calls


def test_synthesis_adds_to_the_same_tally():
    usage = TokenUsage()
    class Answering:
        max_concurrent_requests = 1

        def chat(self, *args, usage=None, **kwargs):
            usage.add(50, 10)
            return "An answer [1]."

    synthesize_insight(Answering(), "q", [{"id": 1, "name": "x"}], usage=usage)

    assert (usage.calls, usage.input_tokens) == (1, 50)
