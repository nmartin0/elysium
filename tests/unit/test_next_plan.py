"""The whole plan in one model call, and nothing else accepted.

AL-4, commit 2 of 4. `next_plan()` asks once for every step, and the
planner is never shown a value -- there is no `gathered` here, which
is the point rather than an omission. A planted instruction in a field
value cannot change WHICH steps run, because the steps are chosen
before any field is read.

WHAT THIS FILE MOSTLY TESTS IS REFUSAL. A plan runs unattended: by the
time a bad step executes, the steps before it have already read real
data and written real audit entries. Everything wrong with a plan has
to be found before the first read.
"""

import json

import pytest

from core.llm.agent_step_prompt import PLAN_INSTRUCTIONS, next_plan, validated_step
from core.llm.interface import LLMUnavailable
from core.llm.plan import PlanError

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "fields": {
            "name": {"type": "data", "data_type": "string"},
            "transactions": {"type": "link", "target": "Transaction"},
        },
    },
    "Transaction": {
        "id_field": "transaction_id",
        "fields": {"amount": {"type": "data", "data_type": "decimal"}},
    },
}

GOOD_PLAN = {
    "plan": [
        {"id": "a", "step": "search_object", "object_type": "Customer",
         "filter": {"name": "Ada Okafor"}},
        {"id": "b", "step": "get_field", "object_type": "Customer",
         "object_id": "$a", "field_name": "name"},
    ]
}


class Fixed:
    max_concurrent_requests = 1

    def __init__(self, reply):
        self.reply = reply if isinstance(reply, str) else json.dumps(reply)
        self.system_prompt = None
        self.user_message = None

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        self.system_prompt = system_prompt
        self.user_message = user_message
        return self.reply


class Unavailable:
    max_concurrent_requests = 1

    def chat(self, *a, **k):
        raise LLMUnavailable("the model is down")


def _plan(reply, client=None):
    client = client or Fixed(reply)
    return next_plan(client, "what did Ada spend?", SCHEMA, [], False, {})


# ------------------------------------------------------------ the happy path


def test_a_good_plan_comes_back_whole():
    plan = _plan(GOOD_PLAN)

    assert [step["id"] for step in plan] == ["a", "b"]
    assert plan[1]["object_id"] == "$a"


def test_the_planner_is_never_shown_a_value():
    """THE SECURITY PROPERTY, asserted rather than described.

    There is no `gathered` in a planning call. If a value could reach
    this prompt, a planted instruction in a field could change which
    steps run -- which is the whole thing AL-4 exists to prevent.
    """
    client = Fixed(GOOD_PLAN)
    _plan(None, client)

    # THE REAL PROPERTY IS THAT NO VALUE IS PRESENT, not that a
    # phrase is absent -- a first version asserted "Gathered so far"
    # appeared nowhere and failed, because AL-2's untrusted-data
    # framing mentions it by name while carrying no data at all.
    assert client.user_message == "Question: what did Ada spend?\n\nWhat is the plan?"
    for value in ("Ada Okafor", "cust_001", "ada.okafor@example.com"):
        assert value not in client.system_prompt

    # NOTED FOR COMMIT 4, not fixed here: AL-2's framing paragraph
    # tells the model to ignore instructions inside values it is
    # shown. In plan mode it is shown none, so the paragraph is
    # addressing something that does not exist -- prompt characters
    # for a warning about an empty set. Removing it now would weaken
    # the step path, which still needs it; it goes when the loop
    # switches over.
    assert "never instructions" in client.system_prompt


def test_the_plan_prompt_is_the_step_prompt_plus_instructions():
    """ONE DESCRIPTION OF THE SCHEMA, TOOLS AND ACTIONS.

    A second one would drift, and a plan written against a schema the
    executor does not share is a plan that fails after real reads.
    """
    client = Fixed(GOOD_PLAN)
    _plan(None, client)

    assert client.system_prompt.endswith(PLAN_INSTRUCTIONS)
    # ...and the schema is still in there, from the shared builder.
    assert "Customer" in client.system_prompt
    assert "amount (decimal)" in client.system_prompt


def test_the_instructions_explain_handles():
    """The model cannot use `$a` if nothing tells it the syntax."""
    assert "$a" in PLAN_INSTRUCTIONS
    assert "BACKWARDS" in PLAN_INSTRUCTIONS.upper()


# ----------------------------------------------------------------- refusals


def test_an_unparseable_reply_is_refused():
    with pytest.raises(PlanError, match="unparseable_reply"):
        _plan("not json at all")


def test_a_reply_that_is_not_an_object_is_refused():
    with pytest.raises(PlanError, match="unparseable_reply"):
        _plan("[1, 2, 3]")


def test_a_reply_with_no_plan_key_is_refused():
    with pytest.raises(PlanError):
        _plan({"steps": []})


def test_a_step_missing_required_keys_is_refused():
    """SAME CHECK THE LIVE PATH USES. A shape accepted here and
    refused there would fail halfway through a plan, with the reads
    before it already done and already audited."""
    with pytest.raises(PlanError, match="not usable"):
        _plan({"plan": [{"id": "a", "step": "get_field",
                         "object_type": "Customer"}]})


def test_an_unrecognised_step_kind_is_refused():
    with pytest.raises(PlanError, match="not usable"):
        _plan({"plan": [{"id": "a", "step": "teleport_object"}]})


def test_a_finish_inside_a_plan_is_refused():
    """A PLAN HAS NOTHING TO FINISH. It ends when its last step does,
    and a finish inside one is the model misreading the instructions
    or padding -- either of which would execute as a no-op and look
    like success."""
    with pytest.raises(PlanError, match="is a finish"):
        _plan({"plan": [
            {"id": "a", "step": "search_object", "object_type": "Customer",
             "filter": {}},
            {"id": "b", "step": "finish"},
        ]})


def test_a_forward_handle_is_refused_before_anything_runs():
    with pytest.raises(PlanError, match="before them"):
        _plan({"plan": [
            {"id": "a", "step": "get_field", "object_type": "Customer",
             "object_id": "$b", "field_name": "name"},
            {"id": "b", "step": "search_object", "object_type": "Customer",
             "filter": {}},
        ]})


def test_an_outage_is_raised_rather_than_becoming_an_empty_plan():
    """UNLIKE next_step(), WHICH FINISHES.

    That call has real gathered context to answer from, so finishing
    is the better of two bad options. A plan that was never written
    has nothing to execute, so the caller must see the outage rather
    than an empty plan that would read as "nothing to do".
    """
    with pytest.raises(LLMUnavailable):
        _plan(None, Unavailable())


# --------------------------------------------- the shared validation itself


def test_validated_step_is_the_same_function_both_paths_use():
    """EXTRACTED, NOT COPIED. Two copies of the step-shape chain would
    drift, and the drift would be silent."""
    good = validated_step({"step": "search_object", "object_type": "Customer",
                           "filter": {}})
    bad = validated_step({"step": "get_field", "object_type": "Customer"})

    assert good["step"] == "search_object"
    assert bad["step"] == "finish"
    assert bad["fallback"] == "malformed_step"


def test_the_instructions_teach_the_list_form():
    """FOUND BY THE FIRST REAL FAN-OUT RUN. The instructions only ever
    showed a handle in a SCALAR position -- `"object_id": "$a"` -- so
    the model generalised to `["$b"]` for a list one. Reasonable
    inference, wrong answer, and my prompt under-specified it.

    The executor now refuses that shape, but a refusal costs a whole
    extra planning call at ~60-280s. Teaching it is the cheaper half.
    """
    assert '"object_ids": "$b"' in PLAN_INSTRUCTIONS
    assert '["$b"]' in PLAN_INSTRUCTIONS
    assert "NOT" in PLAN_INSTRUCTIONS


def test_a_plan_may_put_a_handle_where_the_live_path_needs_a_list():
    """THE EXACT PLAN THE MODEL WROTE ON THE VM, once the instructions
    taught it the right form -- and which next_plan() then rejected.

    A control caught that this file did not cover it: every other test
    here uses a handle in a SCALAR position, so validating plan steps
    without allow_handles changed nothing and the guard passed against
    broken code. Going through next_plan() rather than calling
    validated_step() directly is what makes the difference visible.
    """
    plan = _plan({"plan": [
        {"id": "a", "step": "search_object", "object_type": "Customer",
         "filter": {"name": "Ada Okafor"}},
        {"id": "b", "step": "get_field", "object_type": "Customer",
         "object_id": "$a", "field_name": "transactions"},
        {"id": "c", "step": "get_object", "object_type": "Transaction",
         "object_ids": "$b", "field_names": ["amount"]},
    ]})

    assert [step["id"] for step in plan] == ["a", "b", "c"]
    assert plan[2]["object_ids"] == "$b"


def test_a_plan_with_a_genuinely_empty_list_is_still_refused():
    """The opposite direction: allowing a HANDLE where a list belongs
    must not allow anything else. An empty object_ids is structurally
    malformed whether or not handles are permitted."""
    with pytest.raises(PlanError, match="not usable"):
        _plan({"plan": [
            {"id": "a", "step": "get_object", "object_type": "Customer",
             "object_ids": [], "field_names": ["email"]},
        ]})
