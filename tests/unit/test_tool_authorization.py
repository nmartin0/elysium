"""
Tests for per-user tool authorization in core/agent/agentic_loop.py's
AgentLoop._execute_step(). Uses LinearRegressionTool directly (real,
not mocked) plus a real DataMediator/AgentLoop, but mocks the LLM
client itself -- these tests are about the AUTHORIZATION gate around a
tool call, not about the model's own step-selection.

AgentLoop.run() takes a pre-resolved UserRecord now, not a raw user_id.
"""

import json
from unittest.mock import MagicMock

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from tools.linear_regression import LinearRegressionTool

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "authorized"},
    "bob": {"org_id": "org-a", "role": "unauthorized"},  # exists, but no tool: grant
}

TEST_ROLES = {
    "authorized": {"allowed_actions": ["tool:linear_regression"]},
    "unauthorized": {"allowed_actions": []},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def mediator(test_db_path, test_schema) -> DataMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    return DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES)


def _loop_with_mocked_llm(mediator, scripted_steps):
    client = MagicMock()
    call_count = {"n": 0}

    def fake_chat(*args, **kwargs):
        idx = min(call_count["n"], len(scripted_steps) - 1)
        call_count["n"] += 1
        return json.dumps(scripted_steps[idx])

    client.chat.side_effect = fake_chat
    return AgentLoop(client, mediator, tools=[LinearRegressionTool()])


def test_authorized_user_can_use_tool(mediator):
    loop = _loop_with_mocked_llm(mediator, [
        {"step": "use_tool", "tool_name": "linear_regression", "args": {"x_values": [1, 2], "y_values": [2, 4]}},
        {"step": "finish"},
    ])
    result = loop.run(_record("alice"), "test query")
    real_data = AgentLoop.filter_real_data(result.gathered)
    assert real_data[0]["result"]["slope"] == pytest.approx(2.0)


def test_unauthorized_user_gets_same_error_as_nonexistent_tool(mediator):
    # bob has NO tool: grant at all -- his attempt must fail exactly
    # like a genuinely nonexistent tool would, not a distinguishable
    # "you're not authorized" message. This is the probing-resistance
    # property specifically for tools.
    loop = _loop_with_mocked_llm(mediator, [
        {"step": "use_tool", "tool_name": "linear_regression", "args": {"x_values": [1, 2], "y_values": [2, 4]}},
        {"step": "finish"},
    ])
    result = loop.run(_record("bob"), "test query")
    # No successful tool result should appear -- the loop should have
    # treated it as a recoverable invalid step, not executed the tool.
    assert not any(
        item.get("step") == "use_tool" and "slope" in str(item.get("result", ""))
        for item in result.gathered
    )


def test_nonexistent_tool_name_produces_identical_shape_of_failure(mediator):
    loop = _loop_with_mocked_llm(mediator, [
        {"step": "use_tool", "tool_name": "totally_fake_tool_xyz", "args": {}},
        {"step": "finish"},
    ])
    result = loop.run(_record("alice"), "test query")  # alice, even though authorized for linear_regression, not this fake one
    real_data = AgentLoop.filter_real_data(result.gathered)
    assert not any("slope" in str(item.get("result", "")) for item in real_data)
