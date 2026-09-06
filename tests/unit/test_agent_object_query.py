"""
Point 17: aggregation and link traversal as agent steps.

FOUNDRY'S PRECEDENT is precise here. Their Agent Studio has exactly
four tool types, and the Object query tool "supports filtering,
aggregation, inspection, and traversal of links for configured
objects". Elysium's agent had filtering (search_object) and inspection
(get_field, get_object) and neither of the other two -- so the
primitives built in Points 6 and 7, exposed over HTTP in Point 11,
were unreachable to the agent that most needed them.

WHAT THIS CHANGES BEHAVIOURALLY, which matters more than the step
count. Asked for a total, the loop previously had to HOP -- one
get_field per matching object, one step each. That is correct but
slow, token-hungry, and capped by the step budget on any real dataset:
a question over a thousand objects simply could not be answered. One
aggregate_object answers it in a single step.

The same holds for traversal: "every transaction belonging to a
us-west customer" was one lookup per customer, and is now one step.

NOT A REWORK. The loop's dispatch is a table mapping each step to a
mediator method, which is the intended extension point -- the
architecture was sound, its vocabulary was just narrower than the
mediator's.
"""

import sqlite3

import pytest
import yaml

from core.agent.agentic_loop import AgentLoop, _step_signature
from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator

FIXTURES = "tests/integration/fixtures/"
WEST = UserRecord(user_id="a", security_value="us-west", role_name="customer_service")
EAST = UserRecord(user_id="b", security_value="us-east", role_name="customer_service")


@pytest.fixture
def loop_and_mediator(tmp_path):
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )

    db_path = tmp_path / "business.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    conn.commit()
    conn.close()

    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": db_path}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    object_types = {
        name: type_def
        for name, type_def in schema["object_types"].items()
        if name in ("Customer", "Transaction", "Tag")
    }
    mediator = DataMediator(
        object_types, adapters, dict.fromkeys(object_types, "primary_sql"), policy["roles"]
    )
    return AgentLoop(client=None, mediator=mediator), mediator


def _run(loop, mediator, step, user=WEST):
    gathered: list[dict] = []
    loop._execute_step(step, user, mediator.visible_schema(user), gathered, 0, 0)
    return gathered[-1]["result"] if gathered else None


def test_the_agent_can_aggregate_with_grouping(loop_and_mediator):
    loop, mediator = loop_and_mediator

    result = _run(loop, mediator, {
        "step": "aggregate_object", "object_type": "Transaction",
        "aggregate": "sum", "field_name": "amount", "group_by": "category",
    })

    assert result["hardware"] == 199.0


def test_the_agent_can_count_a_whole_set_in_one_step(loop_and_mediator):
    # The hop this replaces: counting previously meant a search plus a
    # read per object.
    loop, mediator = loop_and_mediator

    result = _run(loop, mediator, {
        "step": "aggregate_object", "object_type": "Customer", "aggregate": "count",
    })

    assert result == {None: 2}


def test_the_agent_can_traverse_a_link(loop_and_mediator):
    loop, mediator = loop_and_mediator

    result = _run(loop, mediator, {
        "step": "search_around", "object_type": "Customer",
        "filter": {"region": "us-west"}, "link_field": "transactions",
    })

    assert sorted(result) == [1, 2, 3, 4]


def test_a_filter_is_optional_on_both_new_steps(loop_and_mediator):
    # An omitted filter means "every object of this type I can see",
    # which is a legitimate and common request rather than an error.
    loop, mediator = loop_and_mediator

    assert _run(loop, mediator, {
        "step": "search_around", "object_type": "Customer", "link_field": "transactions",
    })


def test_the_new_steps_respect_mac(loop_and_mediator):
    # These are new agent surface over data reachable only through MAC.
    # A more convenient path that authorized MORE would be a
    # regression, not a feature.
    loop, mediator = loop_and_mediator

    west = _run(loop, mediator, {
        "step": "aggregate_object", "object_type": "Transaction", "aggregate": "count",
    }, user=WEST)
    east = _run(loop, mediator, {
        "step": "aggregate_object", "object_type": "Transaction", "aggregate": "count",
    }, user=EAST)

    assert west != east


def test_repeating_a_set_based_step_is_detected_as_duplicate_work():
    # Both steps are deterministic for the same inputs, so repeating
    # one wastes a step exactly as a repeated get_field does.
    first = _step_signature({
        "step": "aggregate_object", "object_type": "Transaction",
        "aggregate": "sum", "field_name": "amount", "group_by": "category",
    })
    same = _step_signature({
        "step": "aggregate_object", "object_type": "Transaction",
        "aggregate": "sum", "field_name": "amount", "group_by": "category",
    })
    different = _step_signature({
        "step": "aggregate_object", "object_type": "Transaction",
        "aggregate": "count", "field_name": None, "group_by": None,
    })

    assert first == same
    assert first != different


def test_search_around_signatures_distinguish_the_link_field():
    a = _step_signature({"step": "search_around", "object_type": "Customer",
                         "link_field": "transactions"})
    b = _step_signature({"step": "search_around", "object_type": "Customer",
                         "link_field": "support_tickets"})

    assert a != b


def test_both_new_steps_are_advertised_in_the_prompt():
    # A capability the model is never told about might as well not
    # exist -- the dispatch and the prompt must stay in step.
    source = open("core/llm/agent_step_prompt.py").read()

    assert "aggregate_object" in source
    assert "search_around" in source
