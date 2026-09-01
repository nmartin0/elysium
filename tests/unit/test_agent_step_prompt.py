"""
Tests for core/llm/agent_step_prompt.py's next_step() -- the JSON-
parsing and structural-validation layer between a real model's raw
response and the step dict core/agent/agentic_loop.py actually
executes. No dedicated test file existed for this core parsing logic
at all before this one (search_object/get_field/finish were only ever
exercised indirectly, through full AgentLoop.run() calls elsewhere) --
this file's own primary motivation was get_object's own new parsing
branch, but it's scoped to cover the general "fails closed on any
uncertainty" contract too, not just the one new step type.

Uses a bare MagicMock for the LLM client (client.chat() returns
whatever JSON string each test scripts) -- next_step() itself has no
real HTTP dependency to isolate away, unlike full AgentLoop tests.
"""

import json
from unittest.mock import MagicMock

from core.llm.agent_step_prompt import next_step

VISIBLE_SCHEMA = {
    "Widget": {
        "id_field": "widget_id",
        "fields": {"name": {"type": "data"}},
    },
}


def _client_returning(content) -> MagicMock:
    client = MagicMock()
    client.chat.return_value = content if isinstance(content, str) else json.dumps(content)
    return client


def _next_step(content):
    return next_step(_client_returning(content), "a query", VISIBLE_SCHEMA, [], [], False, {})


def test_finish_step_parses_correctly():
    assert _next_step({"step": "finish"}) == {"step": "finish"}


def test_search_object_step_parses_correctly():
    step = {"step": "search_object", "object_type": "Widget", "filter": {"name": "x"}}
    assert _next_step(step) == step


def test_get_field_step_parses_correctly():
    step = {"step": "get_field", "object_type": "Widget", "object_id": "w1", "field_name": "name"}
    assert _next_step(step) == step


def test_malformed_json_fails_closed_to_finish():
    assert _next_step("not valid json{{{") == {"step": "finish"}


def test_unrecognized_step_fails_closed_to_finish():
    assert _next_step({"step": "totally_made_up_step"}) == {"step": "finish"}


def test_get_field_missing_a_required_key_fails_closed():
    # No "field_name" -- structurally incomplete for this step's own shape.
    step = {"step": "get_field", "object_type": "Widget", "object_id": "w1"}
    assert _next_step(step) == {"step": "finish"}


# --- get_object -------------------------------------------------------------

def test_get_object_step_parses_correctly():
    step = {"step": "get_object", "object_type": "Widget", "object_id": "w1", "field_names": ["name", "widget_id"]}
    assert _next_step(step) == step


def test_get_object_missing_a_required_key_fails_closed():
    step = {"step": "get_object", "object_type": "Widget", "object_id": "w1"}  # no field_names
    assert _next_step(step) == {"step": "finish"}


def test_get_object_with_empty_field_names_fails_closed():
    # Deliberately rejected, not treated as "read nothing" -- see
    # this module's own comment on why: an empty list would otherwise
    # silently produce ZERO gathered[] entries in core/agent/
    # agentic_loop.py, a confusing no-op the model gets no feedback
    # from at all.
    step = {"step": "get_object", "object_type": "Widget", "object_id": "w1", "field_names": []}
    assert _next_step(step) == {"step": "finish"}


def test_get_object_with_non_list_field_names_fails_closed():
    # A model hallucinating field_names as a bare string instead of a
    # list -- structurally wrong, not silently coerced into a
    # single-element list.
    step = {"step": "get_object", "object_type": "Widget", "object_id": "w1", "field_names": "name"}
    assert _next_step(step) == {"step": "finish"}
