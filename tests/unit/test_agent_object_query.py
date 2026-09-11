
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

import os
import sqlite3
import stat
import tempfile
from pathlib import Path

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


# --- Auto-execute (Foundry parity) --------------------------------------


@pytest.fixture
def write_loop(tmp_path):
    from core.ontology.write_log import WriteLogWriter
    from core.ontology.write_mediator import WriteMediator

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
        if name in ("Customer", "Account")
    }
    mediator = DataMediator(
        object_types, adapters, dict.fromkeys(object_types, "primary_sql"),
        policy["roles"], write_log=WriteLogWriter(tmp_path / "wl.db"),
    )

    def build(auto_execute=None):
        action_types = {
            name: (dict(action, auto_execute=auto_execute) if auto_execute is not None
                   else dict(action))
            for name, action in schema["action_types"].items()
        }
        write_mediator = WriteMediator(mediator, adapters, policy["roles"], action_types, generation=1)
        return AgentLoop(client=None, mediator=mediator, write_mediator=write_mediator), mediator

    return build


TRANSFER = {
    "step": "propose_action", "action_type": "TransferFunds",
    "parameters": {
        "from_account_id": "acc_checking", "to_account_id": "acc_savings",
        "new_from_balance": 900, "new_to_balance": 600,
    },
}
ACCOUNTANT = UserRecord(user_id="u", security_value="us-west", role_name="accountant")


def test_the_default_is_to_pause_for_confirmation(write_loop):
    # A deployment that says nothing gets the safe behaviour.
    loop, mediator = write_loop()
    gathered: list[dict] = []

    _c, _b, _f, pending = loop._execute_step(
        TRANSFER, ACCOUNTANT, mediator.visible_schema(ACCOUNTANT), gathered, 0, 0
    )

    assert pending is not None, "a write ran without confirmation by default"
    assert mediator.get_field(ACCOUNTANT, "Account", "acc_checking", "balance") == 500.0


def test_auto_execute_writes_without_a_confirmation_step(write_loop):
    # Foundry's Action tool "can be configured to run automatically or
    # to run after confirmation from the user".
    loop, mediator = write_loop(auto_execute=True)
    gathered: list[dict] = []

    _c, _b, _f, pending = loop._execute_step(
        TRANSFER, ACCOUNTANT, mediator.visible_schema(ACCOUNTANT), gathered, 0, 0
    )

    assert pending is None
    assert gathered[-1]["result"]["status"] == "auto_executed"
    assert mediator.get_field(ACCOUNTANT, "Account", "acc_checking", "balance") == 900


def test_auto_execute_false_is_the_same_as_absent(write_loop):
    loop, mediator = write_loop(auto_execute=False)
    gathered: list[dict] = []

    _c, _b, _f, pending = loop._execute_step(
        TRANSFER, ACCOUNTANT, mediator.visible_schema(ACCOUNTANT), gathered, 0, 0
    )

    assert pending is not None


def test_the_model_cannot_request_auto_execution(write_loop):
    # THE property that makes this enforceable. The flag is read from
    # the DEPLOYMENT's action type, never from the step the model
    # emitted -- a model that could ask to skip confirmation would make
    # the setting advisory, and the whole point is that it is not.
    loop, mediator = write_loop()
    gathered: list[dict] = []

    _c, _b, _f, pending = loop._execute_step(
        {**TRANSFER, "auto_execute": True},
        ACCOUNTANT, mediator.visible_schema(ACCOUNTANT), gathered, 0, 0
    )

    assert pending is not None, "the model talked its way past confirmation"
    assert mediator.get_field(ACCOUNTANT, "Account", "acc_checking", "balance") == 500.0


def test_a_non_boolean_auto_execute_is_rejected_at_load():
    from core.ontology.action_types import _validate_auto_execute

    with pytest.raises(ValueError, match="must be true or false"):
        _validate_auto_execute("Bad", {"auto_execute": "yes"})


def test_a_delete_goes_from_the_agents_prompt_through_to_applied(write_loop):
    """The whole path: a delete action type reaches the agent, the
    agent proposes it, confirming applies it, and the object is gone
    from reads while its row survives in the source database.

    ABANDONED ONCE, and the reason is worth recording. A first attempt
    was denied at the MAC check and I could not explain it -- the
    security value resolved correctly when called directly. The cause
    was in the fixture, not the authorization: the sub_write said
    `object_id: $account_id`, which is not a parameter reference. Only
    strings beginning "parameter." are expanded, so MAC was asked
    whether the caller could modify an Account whose id is the literal
    characters "$account_id". No such object exists, so it correctly
    said no.

    The authorization layer was right and my fixture was wrong, which
    is the opposite of what I assumed at the time. The validation
    added since now rejects that form outright.
    """
    from core.llm.agent_step_prompt import _describe_actions

    loop, mediator = write_loop()
    delete_action = {
        "affected_object_types": ["Account"],
        "parameters": {
            "account_id": {"type": "object_reference", "object_type": "Account"}
        },
        "sub_writes": [
            {
                "object_type": "Account",
                "object_id": "parameter.account_id",
                "operation": "delete",
            }
        ],
        "executable": True,
    }

    # It reaches the prompt from the deployment's own declaration, with
    # no code change.
    described = _describe_actions({"RemoveAccount": delete_action})
    assert "RemoveAccount" in described
    assert "propose_action" in described

    loop.write_mediator.action_types["RemoveAccount"] = delete_action
    loop.write_mediator.roles["accountant"]["allowed_actions"].append("execute:RemoveAccount")

    gathered: list[dict] = []
    _c, _b, _f, pending = loop._execute_step(
        {
            "step": "propose_action", "action_type": "RemoveAccount",
            "parameters": {"account_id": "acc_checking"},
        },
        ACCOUNTANT, mediator.visible_schema(ACCOUNTANT), gathered, 0, 0,
    )

    assert pending is not None, "a delete should still pause for confirmation"
    loop.write_mediator.confirm_and_execute(pending, approved=True)

    # Gone from reads...
    assert mediator.get_field(ACCOUNTANT, "Account", "acc_checking", "balance") is None
    # ...and the source row untouched, which is what makes a delete here
    # an edit rather than destruction.
    adapter = mediator.adapters["primary_sql"]
    conn = sqlite3.connect(adapter.db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM accounts WHERE account_id = 'acc_checking'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_a_delete_action_type_reaches_the_agents_prompt(write_loop):
    """Point 13 built the delete operation; Point 17 established that
    action types reach the prompt from the deployment's own
    declaration with no code change. This asserts that specifically
    for a DELETE, which the two points never exercised together.

    Scoped to the prompt half deliberately. Applying a delete through
    confirm_and_execute() is already covered by
    tests/unit/test_delete_operation.py; what was genuinely unproven
    was whether a delete ACTION TYPE is visible to the agent at all.
    Driving a full propose-and-apply through the loop needs a fixture
    whose parameter resolution and MAC chain are set up for it, and is
    recorded in ROADMAP.md rather than half-built here.
    """
    from core.llm.agent_step_prompt import _describe_actions

    delete_action = {
        "affected_object_types": ["Account"],
        "parameters": {
            "account_id": {"type": "object_reference", "object_type": "Account"}
        },
        "sub_writes": [
            {"object_type": "Account", "object_id": "$account_id", "operation": "delete"}
        ],
        "executable": True,
    }

    described = _describe_actions({"RemoveAccount": delete_action})

    assert "RemoveAccount" in described
    assert "propose_action" in described
    assert "account_id" in described


def test_a_type_error_is_logged_as_a_likely_bug_not_just_a_bad_step(caplog):
    """A TypeError from _execute_step is far more likely OUR bug than
    the model's. Treated as a plain recoverable mistake it becomes
    invisible -- the model is told its step was invalid, retries, fails
    again, and the loop stops with "too many consecutive invalid
    steps" while the real defect never surfaces.

    Still recovered rather than raised (a model CAN provoke one, and
    crashing a user's query on an ambiguous signal is worse), but
    logged at ERROR with a traceback so it is findable.
    """
    import logging

    class ExplodingMediator:
        roles: dict = {}
        schema: dict = {}

        def visible_schema(self, user_record):
            return {}

        def search_object(self, *args, **kwargs):
            raise TypeError("wrong arity -- a real bug, not a bad step")

    loop = AgentLoop(client=None, mediator=ExplodingMediator())
    gathered: list[dict] = []

    with caplog.at_level(logging.ERROR):
        loop._execute_step(
            {"step": "search_object", "object_type": "Customer", "filter": {}},
            WEST, {}, gathered, 0, 0,
        )

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a TypeError was recovered with no error-level record"
    assert "likely a bug" in errors[0].message
    assert errors[0].exc_info, "the traceback is what makes it findable"


def test_a_value_error_is_still_treated_as_an_ordinary_bad_step(caplog):
    # The distinction has to hold both ways: a ValueError IS usually
    # the model's fault, and logging every one at error level would
    # bury the TypeErrors again.
    import logging

    class RejectingMediator:
        roles: dict = {}
        schema: dict = {}

        def visible_schema(self, user_record):
            return {}

        def search_object(self, *args, **kwargs):
            raise ValueError("no such field")

    loop = AgentLoop(client=None, mediator=RejectingMediator())
    gathered: list[dict] = []

    with caplog.at_level(logging.DEBUG):
        loop._execute_step(
            {"step": "search_object", "object_type": "Customer", "filter": {}},
            WEST, {}, gathered, 0, 0,
        )

    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


# --- Unreachable backend vs unparseable answer ---------------------------
#
# Found by a real integration run, not by reasoning. An 8-minute read
# timeout against a local model produced `gathered: []` and a normal
# finish -- so the trace read as "the model chose to do nothing" when
# the truth was "the model never answered". The handler caught
# requests.RequestException, json.JSONDecodeError and KeyError
# together and finished on all three.
#
# Those are different events. An unparseable answer means the model
# spoke and there is real gathered context to work with; an
# unreachable backend means there is nothing, and saying "here is your
# answer" is a fabrication.


def test_an_unreachable_backend_raises_rather_than_finishing():
    # THE bug. Finishing here hands the user a confident-looking answer
    # assembled from zero data, with nothing to indicate the model was
    # never reached.
    from core.llm.agent_step_prompt import next_step
    from core.llm.interface import LLMUnavailable

    class UnreachableClient:
        max_concurrent_requests = 1

        def chat(self, *args, **kwargs):
            raise LLMUnavailable("read timed out after 480s")

    with pytest.raises(LLMUnavailable, match="read timed out"):
        next_step(UnreachableClient(), "q", {}, [], [], True, {})


def test_an_unparseable_answer_still_finishes():
    # The other half, and it must keep working: the model DID answer,
    # there is gathered context, and the best available answer beats an
    # error.
    from core.llm.agent_step_prompt import next_step

    class GarbageClient:
        max_concurrent_requests = 1

        def chat(self, *args, **kwargs):
            return "this is not json at all"

    step = next_step(GarbageClient(), "q", {}, [], [], True, {})

    assert step["step"] == "finish"


def test_both_adapters_raise_the_same_type_for_an_unreachable_backend():
    """The handler previously caught requests.RequestException -- one
    adapter's transport library. A second adapter raising anything else
    went entirely unhandled, so an Ollama failure was swallowed while
    an identical Claude failure propagated. Same event, opposite
    behaviour, decided by which backend was configured.

    Asserts the adapters actually RAISE it. A first version checked
    that "LLMUnavailable" appeared in each module's source, which a
    comment satisfies -- proven by replacing the raise with a
    RuntimeError and leaving the word behind, after which it still
    passed.
    """
    import adapters.claude_agent_sdk_adapter as claude_module
    from adapters.ollama_adapter import OllamaAdapter
    from core.llm.interface import LLMUnavailable

    # Ollama: a base_url nothing is listening on.
    ollama = OllamaAdapter("m", {"base_url": "http://127.0.0.1:9/api/chat",
                                 "request_timeout_seconds": 1})
    with pytest.raises(LLMUnavailable):
        ollama.chat("sys", "hi")

    # Claude: a CLI that exits non-zero.
    script = Path(tempfile.mkdtemp()) / "claude"
    script.write_text("#!/bin/sh\necho 'not signed in' >&2\nexit 1\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    original_path = os.environ["PATH"]
    os.environ["PATH"] = f"{script.parent}{os.pathsep}{original_path}"
    try:
        with pytest.raises(LLMUnavailable, match="not signed in"):
            claude_module.ClaudeAgentSDKAdapter("m", {}).chat("sys", "hi")
    finally:
        os.environ["PATH"] = original_path



def test_a_wider_get_object_is_not_treated_as_a_duplicate():
    """A get_field followed by a get_object including that field must
    NOT be flagged as duplicate work.

    A detected duplicate is REJECTED -- the step does not execute and
    enough of them stop the loop -- so flagging this would block a
    step that returns fields the model does not have yet, then end the
    run for persisting. The roadmap listed it as a gap; it is the
    correct behaviour, and this pins it.
    """
    from core.agent.agentic_loop import _step_signature

    narrow = _step_signature(
        {"step": "get_field", "object_type": "Customer",
         "object_id": "cust_001", "field_name": "name"}
    )
    wider = _step_signature(
        {"step": "get_object", "object_type": "Customer",
         "object_id": "cust_001", "field_names": ["name", "email"]}
    )

    assert narrow != wider, (
        "a wider get_object matched an earlier get_field's signature -- it "
        "would be rejected as a duplicate despite returning new fields"
    )


def test_an_identical_get_object_is_still_caught():
    # The distinction has to hold: repeating the SAME request is what
    # duplicate detection exists for.
    from core.agent.agentic_loop import _step_signature

    step = {"step": "get_object", "object_type": "Customer",
            "object_id": "cust_001", "field_names": ["name", "email"]}

    assert _step_signature(step) == _step_signature(dict(step))


# --- Step dispatch -------------------------------------------------------


def test_an_unknown_step_kind_stops_without_counting_a_mistake(loop_and_mediator):
    """A step outside the schema entirely is not a recoverable mistake.

    The invalid-step counter exists for a model that produced a
    well-formed step with bad arguments -- a nudge and a retry. A step
    kind that does not exist means the output was not the shape asked
    for at all, so the loop stops rather than nudging.

    Uncovered before the dispatch table, and still uncovered after,
    which is how it was found: the coverage rule counts a moved line as
    a touched one.
    """
    loop, mediator = loop_and_mediator
    gathered: list[dict] = []

    invalid, business, stop, pending = loop._execute_step(
        {"step": "teleport_object", "object_type": "Customer"},
        WEST, mediator.visible_schema(WEST), gathered, 3, 2,
    )

    assert stop is True
    assert pending is None
    # Counters pass through unchanged -- nothing was attempted, so
    # nothing succeeded or failed.
    assert (invalid, business) == (3, 2)
    assert gathered == []


def test_every_declared_step_kind_has_a_handler(loop_and_mediator):
    """The table and the prompt must agree.

    A step kind the prompt offers but the table lacks would fall into
    the unknown-step branch and stop the loop -- the model doing
    exactly as instructed and being refused for it. Cheap to check
    here, expensive to notice in a trace.
    """
    import re
    from pathlib import Path

    loop, _ = loop_and_mediator
    prompt = Path("core/llm/agent_step_prompt.py").read_text()
    offered = set(re.findall(r'"step": "([a-z_]+)"', prompt))

    # `finish` ends the loop rather than executing, so it is handled by
    # run() and not by the dispatch table.
    assert offered - {"finish"} == set(loop._step_handlers())
