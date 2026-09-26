"""A plan runs unattended, and says structurally when it cannot.

AL-4, commit 3 of 4. `execute_plan()` runs a validated plan in order,
resolving each handle from what earlier steps produced, and returns
None or a STRUCTURAL description of what stopped it -- "returned 0
results", "would read 34 objects, over the limit of 20". Never a
value.

THAT DISTINCTION IS THE WHOLE OF SHAPE B. Commit 4 hands the string
back to the planner so it can revise. A planted instruction in a field
cannot express itself through a count, so re-planning on structure
keeps the property that re-planning on values would give away.

REAL MEDIATOR, NOT A MOCK. 001AGENTLOOP records that the decimal crash
reached the shipped configuration because agent tests mock the
mediator and hand back floats and strings. Fan-out is about real reads
returning real ids, so these do real reads.
"""

import contextlib
import io

import pytest

from core.agent.agentic_loop import MAX_OBJECT_IDS
from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record
from core.llm.plan import MAX_PLAN_FANOUT

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
    assert user.role_name is not None, "the fixture user has no role"
    return generation.loop, user


def _run(loop, user, plan):
    gathered: list[dict] = []
    schema = loop.mediator.visible_schema(user, for_agent=True)
    with contextlib.redirect_stdout(io.StringIO()):
        failure = loop.execute_plan(plan, user, schema, gathered)
    return failure, gathered


SEARCH = {"id": "a", "step": "search_object", "object_type": "Customer",
          "filter": {"region": "us-west"}}


# -------------------------------------------------------------- it executes


def test_a_plan_runs_every_step_in_order(loop_and_user):
    loop, user = loop_and_user
    plan = [
        SEARCH,
        {"id": "b", "step": "get_field", "object_type": "Customer",
         "object_id": "cust_001", "field_name": "email"},
    ]

    failure, gathered = _run(loop, user, plan)

    assert failure is None
    assert [e["step"] for e in gathered] == ["search_object", "get_field"]
    assert gathered[1]["result"] == "ada.okafor@example.com"


def test_a_handle_carries_an_earlier_result_into_a_later_step(loop_and_user):
    """THE POINT OF THE WHOLE DESIGN. The plan says `$a`; the executor
    substitutes ids the planner never saw."""
    loop, user = loop_and_user
    plan = [
        SEARCH,
        {"id": "b", "step": "get_field", "object_type": "Customer",
         "object_id": "$a", "field_name": "email"},
    ]

    failure, gathered = _run(loop, user, plan)

    assert failure is None
    emails = [e["result"] for e in gathered if e["step"] == "get_field"]
    assert "ada.okafor@example.com" in emails


def test_one_planned_step_fans_out_across_every_object(loop_and_user):
    """A search returns a list, so `$a` names many objects. Running
    once per object is what the model would have done hop by hop, and
    the only reading that does not silently drop all but the first."""
    loop, user = loop_and_user
    plan = [
        SEARCH,
        {"id": "b", "step": "get_field", "object_type": "Customer",
         "object_id": "$a", "field_name": "email"},
    ]

    _, gathered = _run(loop, user, plan)

    found = [e for e in gathered if e["step"] == "get_field"]
    assert len(found) == len(gathered[0]["result"]) > 1


def test_what_a_step_produced_is_what_it_put_in_gathered(loop_and_user):
    """Read back from `gathered`, not from a return value. Handlers
    append their own entries -- search_object attaches AR-4's titles
    that way -- so the entries a step added ARE its result. Any other
    account of it is free to disagree with what the model is shown."""
    loop, user = loop_and_user

    failure, gathered = _run(loop, user, [SEARCH])

    assert failure is None
    assert gathered[0]["result"] == ["cust_001", "cust_002"]


# ----------------------------------------------------- it refuses structurally


def test_too_many_objects_is_refused_rather_than_paged(loop_and_user):
    """MAX_OBJECT_IDS exists because max_hops bounds how much one query
    may read. A plan has no model left to ask for a smaller batch, so
    paging internally would let one planned step read arbitrarily much
    under a limit written to prevent exactly that."""
    loop, user = loop_and_user
    too_many = [f"cust_{n:03d}" for n in range(MAX_PLAN_FANOUT + 14)]
    plan = [{"id": "a", "step": "get_field", "object_type": "Customer",
             "object_id": too_many, "field_name": "email"}]

    failure, gathered = _run(loop, user, plan)

    assert failure is not None
    assert f"would read {len(too_many)} objects" in failure
    assert f"limit of {MAX_PLAN_FANOUT}" in failure
    assert gathered == [], "it read something before refusing"


def test_the_fanout_cap_matches_the_loop_s_own(loop_and_user):
    """TWO CONSTANTS, ONE NUMBER. core.llm sits below core.agent and
    cannot import MAX_OBJECT_IDS, so the plan vocabulary states it
    again -- and this is what stops the two drifting."""
    assert MAX_PLAN_FANOUT == MAX_OBJECT_IDS


def test_a_failure_names_the_step_and_says_nothing_about_values(loop_and_user):
    """SHAPE B. A planted instruction in a field cannot express itself
    through a step id and a stop reason."""
    loop, user = loop_and_user
    # A MALFORMED FILTER, and finding a case that actually refuses
    # took looking. An unknown field name and an unknown object type
    # both return None -- uniform denial, by design: a caller must not
    # learn that a field or a type exists by being refused it. So most
    # "wrong" values produce None results rather than a failure, and
    # only a structurally invalid step refuses.
    plan = [{"id": "a", "step": "search_object", "object_type": "Customer",
             "filter": {"no_such_field": "x"}}]

    failure, _ = _run(loop, user, plan)

    assert failure is not None
    assert failure.startswith("step 'a'")
    # Says WHAT happened, not what was in the data.
    assert "rejected_invalid_step" in failure


def test_a_list_where_one_value_belongs_is_refused(loop_and_user):
    """`"filter": {"region": "$a"}` with a list is not an equality
    condition, and the filter vocabulary is equality-only until LB-2
    says otherwise. Guessing would turn a type error into a wrong
    answer."""
    loop, user = loop_and_user
    plan = [
        SEARCH,
        {"id": "b", "step": "search_object", "object_type": "Customer",
         "filter": {"region": "$a"}},
    ]

    failure, _ = _run(loop, user, plan)

    assert failure is not None
    assert "takes one value" in failure


def test_a_plan_stops_at_the_step_that_failed(loop_and_user):
    """The steps after it were planned assuming it succeeded.

    AND A REFUSED STEP ENDS A PLAN, however forgiving the live loop
    would be. _execute_step()'s recoverable-mistake path exists so the
    MODEL can be told what it got wrong and try again next hop. A plan
    has no model left -- it is executing decisions already made.

    Found by this test: with no counters accumulating, a refused step
    returned no stop reason and the plan carried on into steps that
    assumed it had worked.
    """
    loop, user = loop_and_user
    plan = [
        {"id": "a", "step": "search_object", "object_type": "Customer",
         "filter": {"no_such_field": "x"}},
        {"id": "b", "step": "get_field", "object_type": "Customer",
         "object_id": "cust_001", "field_name": "email"},
    ]

    failure, gathered = _run(loop, user, plan)

    assert failure is not None
    assert not any(e["step"] == "get_field" for e in gathered)
