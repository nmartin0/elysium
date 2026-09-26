"""A query planned up front, with one revision on structure only.

AL-4, commit 4 of 4. `run_planned()` asks for the whole plan, runs it,
and on a structural failure hands that string back for ONE revision.

A SIBLING OF run(), NOT A REPLACEMENT, and that is a decision rather
than caution. Four features on this branch are already merged and
inert waiting on wiring someone else owns; a config flag would have
been the fifth. As a second entry point it is reachable from
scripts/llm_bench.py today, so it can be MEASURED against run() before
anyone decides which should be the default -- the only honest way to
decide it, since the accuracy literature says neither architecture
wins on its own.

WHAT THIS FILE MOSTLY GUARDS is that the revision is told STRUCTURE
and never a value. That is the entire security property: a planted
instruction in a field cannot express itself through a step id and a
count.
"""

import contextlib
import io

import pytest

from core.agent.agentic_loop import StopReason
from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record

USER_ID = "user_alice"

GOOD_PLAN = (
    '{"plan": [{"id": "a", "step": "get_field", "object_type": "Customer", '
    '"object_id": "cust_001", "field_name": "email"}]}'
)

# Fans out over more objects than MAX_PLAN_FANOUT allows, so the
# executor refuses it structurally.
TOO_WIDE = (
    '{"plan": [{"id": "a", "step": "get_field", "object_type": "Customer", '
    '"object_id": ' + str([f"c{n}" for n in range(40)]).replace("'", '"') +
    ', "field_name": "email"}]}'
)


class Replies:
    max_concurrent_requests = 1

    def __init__(self, *replies):
        self._replies = list(replies)
        self.messages: list[str] = []

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        self.messages.append(user_message)
        return self._replies.pop(0) if self._replies else GOOD_PLAN


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


def _planned(loop, user, client, query="what is Ada's email?"):
    loop.client = client
    with contextlib.redirect_stdout(io.StringIO()):
        return loop.run_planned(user, query)


# --------------------------------------------------------------- it works


def test_a_good_plan_runs_in_one_model_call(loop_and_user):
    """THE POINT. Today's loop needs a call per hop; this needs one."""
    loop, user = loop_and_user
    client = Replies(GOOD_PLAN)

    result = _planned(loop, user, client)

    assert result.stop_reason == StopReason.FINISHED
    assert len(client.messages) == 1
    assert result.gathered[0]["result"] == "ada.okafor@example.com"


def test_the_planner_is_shown_no_data_on_the_first_call(loop_and_user):
    loop, user = loop_and_user
    client = Replies(GOOD_PLAN)

    _planned(loop, user, client)

    assert "ada.okafor@example.com" not in client.messages[0]
    assert "cust_001" not in client.messages[0]


# ------------------------------------------------- the revision, shape B


def test_a_failed_plan_gets_one_revision(loop_and_user):
    loop, user = loop_and_user
    client = Replies(TOO_WIDE, GOOD_PLAN)

    result = _planned(loop, user, client)

    assert len(client.messages) == 2, "it did not re-plan"
    assert result.stop_reason == StopReason.FINISHED


def test_the_revision_is_told_structure_and_nothing_else(loop_and_user):
    """THE SECURITY PROPERTY, asserted.

    The executor produces "step 'a' would read 40 objects, over the
    limit of 20" -- a step id, a count, a limit. Putting a RESULT here
    instead would hand the planner the untrusted data it was designed
    never to see, and the control-flow guarantee would go with it.
    """
    loop, user = loop_and_user
    client = Replies(TOO_WIDE, GOOD_PLAN)

    _planned(loop, user, client)

    revision = client.messages[1]
    assert "did not finish" in revision
    assert "over the limit of" in revision
    # No value from the deployment reaches it.
    for value in ("ada.okafor@example.com", "Ada Okafor", "us-west",
                  "Bram Feldman"):
        assert value not in revision


def test_only_one_revision(loop_and_user):
    """A plan fixed before any data is read is injection-proof by
    construction; every revision is another chance to be wrong the
    same way. And at ~520s for an uncached planning call, a third
    attempt costs more than the query is worth."""
    loop, user = loop_and_user
    client = Replies(TOO_WIDE, TOO_WIDE, GOOD_PLAN)

    result = _planned(loop, user, client)

    assert len(client.messages) == 2, "it tried a third time"
    assert result.stop_reason == StopReason.PLAN_FAILED


def test_what_was_gathered_survives_a_failed_plan(loop_and_user):
    """Those reads happened, were authorised, and are in the audit log.
    Discarding them would lose data the caller was entitled to and
    leave audit entries describing reads nobody can see."""
    loop, user = loop_and_user
    partial = (
        '{"plan": ['
        '{"id": "a", "step": "get_field", "object_type": "Customer", '
        '"object_id": "cust_001", "field_name": "email"}, '
        '{"id": "b", "step": "search_object", "object_type": "Customer", '
        '"filter": {"no_such_field": "x"}}]}'
    )
    client = Replies(partial, partial)

    result = _planned(loop, user, client)

    assert result.stop_reason == StopReason.PLAN_FAILED
    assert any(e.get("result") == "ada.okafor@example.com"
               for e in result.gathered)


# ------------------------------------------------------------- the bounds


def test_a_plan_longer_than_max_hops_is_refused(loop_and_user):
    """max_hops BOUNDS A PLAN TOO. Without this a plan of a hundred
    steps walks straight past the limit that exists to cap how much
    one query may read -- the loop enforces it per hop, and a plan has
    no hops to count."""
    loop, user = loop_and_user
    loop.max_hops = 2
    long_plan = '{"plan": [' + ", ".join(
        f'{{"id": "s{n}", "step": "get_field", "object_type": "Customer", '
        f'"object_id": "cust_001", "field_name": "email"}}' for n in range(5)
    ) + "]}"

    result = _planned(loop, user, Replies(long_plan))

    assert result.stop_reason == StopReason.PLAN_TOO_LONG
    assert result.gathered == [], "it read something before refusing"


def test_an_unusable_plan_is_refused_not_retried_forever(loop_and_user):
    loop, user = loop_and_user

    result = _planned(loop, user, Replies("not json at all"))

    assert result.stop_reason == StopReason.PLAN_REFUSED


def test_a_cancelled_query_stops_before_planning(loop_and_user):
    """Planning is the expensive call -- ~520s uncached on this
    hardware. Checking after it would be checking too late."""
    import threading

    loop, user = loop_and_user
    cancelled = threading.Event()
    cancelled.set()
    client = Replies(GOOD_PLAN)
    loop.client = client

    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run_planned(user, "what is Ada's email?", cancelled)

    assert result.stop_reason == StopReason.CANCELLED
    assert client.messages == [], "it called the model after cancellation"
