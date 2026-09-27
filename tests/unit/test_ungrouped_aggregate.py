"""An ungrouped aggregate is one number, and now looks like one.

`aggregate_by_field()` always returns a mapping of group to value.
With no `group_by` there is one group, keyed by None -- a sentinel
meaning "no grouping". `json.dumps` renders that key as the string
"null", so a model asking for the maximum amount was shown:

    "result": {"null": "199"}

That is LB-5's family: an implementation artifact rendered as
information. "null" is not a group the caller asked about and not a
word anywhere in the ontology.

FOUND WHILE CHECKING WHETHER A HARDER BENCH CASE WAS ANSWERABLE AT
ALL -- "what category was Ada's largest transaction?" needs the
aggregate's value to flow into the next step's filter, and a dict
keyed by None cannot.
"""

import decimal

import pytest

from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record
from core.llm.prompt_values import dumps_gathered

USER_ID = "user_alice"


@pytest.fixture
def loop_and_user(synced_deployment):
    generation = build_generation(
        synced_deployment.config_dir,
        synced_deployment.data_dir,
        synced_deployment.log_dir,
    )
    user = resolve_user_record(
        generation.config.users, USER_ID, generation.config.security_attribute
    )
    assert user.role_name is not None
    return generation.loop, user


def _aggregate(loop, user, **extra):
    step = {"step": "aggregate_object", "object_type": "Transaction",
            "filter": {"customer_id": "cust_001"},
            "aggregate": "max", "field_name": "amount", **extra}
    schema = loop.mediator.visible_schema(user, for_agent=True)
    return loop._step_aggregate_object(step, user, schema, [])


def test_an_ungrouped_aggregate_is_a_bare_value(loop_and_user):
    loop, user = loop_and_user

    result = _aggregate(loop, user)

    assert result == decimal.Decimal("199.000000000")
    assert not isinstance(result, dict)


def test_the_model_never_sees_the_word_null(loop_and_user):
    """THE DEFECT ITSELF. A model asked for a maximum was shown
    {"null": "199"}."""
    loop, user = loop_and_user

    rendered = dumps_gathered(
        [{"step": "aggregate_object", "result": _aggregate(loop, user)}], None
    )

    assert "null" not in rendered
    assert '"199"' in rendered


def test_a_grouped_aggregate_keeps_its_mapping(loop_and_user):
    """The opposite direction. Groups are the point of a grouped
    aggregate, and flattening one would lose every group but one."""
    loop, user = loop_and_user

    result = _aggregate(loop, user, group_by="category")

    assert isinstance(result, dict)
    assert set(result) == {"subscription", "hardware"}


def test_a_grouped_aggregate_with_a_null_group_is_NOT_unwrapped():
    """THE DISTINCTION THAT IS LOAD-BEARING.

    The unwrap is conditioned on `group_by` being ABSENT, not on the
    key being None -- because a GROUPED aggregate can legitimately
    produce a None key when a row's group field is null. Unwrapping
    that would turn "the total for rows with no category" into "the
    total", silently, which is a wrong answer rather than an ugly one.
    """
    from core.agent.agentic_loop import AgentLoop

    class OneNullGroup:
        def aggregate_by_field(self, *a, **k):
            return {None: decimal.Decimal("199")}

    loop = AgentLoop.__new__(AgentLoop)
    loop.mediator = OneNullGroup()
    loop._check_filter_types = lambda *a, **k: None

    grouped = loop._step_aggregate_object(
        {"step": "aggregate_object", "object_type": "Transaction",
         "aggregate": "sum", "field_name": "amount", "group_by": "category"},
        None, {}, [],
    )

    assert grouped == {None: decimal.Decimal("199")}, (
        "a null GROUP was flattened into a bare total"
    )


def test_the_value_can_feed_a_later_filter(loop_and_user):
    """WHY THIS MATTERED BEYOND TIDINESS.

    "What category was Ada's largest transaction?" is answerable by a
    plan only if the aggregate's value can flow into the next step's
    filter. A dict keyed by None cannot; a bare Decimal can -- and the
    planner still never sees it, because it writes $a.
    """
    loop, user = loop_and_user
    schema = loop.mediator.visible_schema(user, for_agent=True)
    gathered: list[dict] = []

    failure = loop.execute_plan([
        {"id": "a", "step": "aggregate_object", "object_type": "Transaction",
         "filter": {"customer_id": "cust_001"}, "aggregate": "max",
         "field_name": "amount"},
        {"id": "b", "step": "search_object", "object_type": "Transaction",
         "filter": {"amount": "$a"}},
        {"id": "c", "step": "get_field", "object_type": "Transaction",
         "object_id": "$b", "field_name": "category"},
    ], user, schema, gathered)

    assert failure is None, failure
    assert gathered[-1]["result"] == "hardware"
