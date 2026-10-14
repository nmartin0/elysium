"""AL-10: a per-question token budget beside the hop count and deadline.

Hops bound the number of model calls and the deadline bounds wall time;
neither bounds what the calls COST. Driven through the real loop with a
model that reports a fixed token count per call.
"""

import pytest

from core.agent.agentic_loop import AgentLoop, StopReason
from core.deployment_loader import _token_budget
from core.request_context import RequestContext


class _Model:
    """Every step asks for one field; each call reports 1,000 tokens."""

    def __init__(self):
        self.calls = 0

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        self.calls += 1
        if usage is not None:
            usage.add(800, 200)
        return ('{"step": "get_field", "object_type": "Customer", '
                f'"object_id": "cust_00{self.calls % 4 + 1}", "field_name": "name"}}')


def _run(mediator, budget):
    model = _Model()
    loop = AgentLoop(model, mediator, max_hops=8, max_consecutive_duplicates=8,
                     max_tokens_per_query=budget)
    context = RequestContext.new(deadline_seconds=300)
    return loop, model, loop.run(_user(), "names?", None, context)


def _user():
    from core.intermediate_layer.auth import UserRecord

    return UserRecord(user_id="u", security_value="us-west", role_name="customer_service")


@pytest.fixture
def mediator(synced_deployment):
    from core.deployment_loader import build_generation

    return build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                            synced_deployment.log_dir).mediator


def test_the_budget_stops_the_next_call_once_spent(mediator):
    _, model, result = _run(mediator, budget=2_500)

    assert result.stop_reason == StopReason.TOKEN_BUDGET
    assert result.hit_token_budget
    assert model.calls == 3  # 1,000 + 1,000 + 1,000 >= 2,500, so no fourth


def test_without_a_budget_the_hops_decide(mediator):
    """THE CONTROL: the same run with no budget goes on."""
    _, model, result = _run(mediator, budget=None)

    assert result.stop_reason != StopReason.TOKEN_BUDGET
    assert model.calls > 3


@pytest.mark.parametrize("declared", [0, -1, "lots", True, 1.5])
def test_a_budget_must_be_a_positive_whole_number(declared):
    with pytest.raises(ValueError, match="max_tokens_per_query"):
        _token_budget(declared)
