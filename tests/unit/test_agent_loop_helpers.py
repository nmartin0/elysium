"""
Tests for the pure-logic helper functions inside core/agent/agentic_loop.py --
no LLM, no I/O, just the duplicate/asymmetry detection logic itself.
These stayed module-level functions (not AgentLoop methods) since they
need no instance state -- pure functions of their arguments only.
"""

from core.agent.agentic_loop import _step_signature, _detect_asymmetry


def test_step_signature_search_object_is_order_independent():
    step_a = {"step": "search_object", "object_type": "Customer", "filter": {"a": 1, "b": 2}}
    step_b = {"step": "search_object", "object_type": "Customer", "filter": {"b": 2, "a": 1}}
    assert _step_signature(step_a) == _step_signature(step_b)


def test_step_signature_get_field_distinguishes_different_fields():
    step_a = {"step": "get_field", "object_type": "T", "object_id": 1, "field_name": "amount"}
    step_b = {"step": "get_field", "object_type": "T", "object_id": 1, "field_name": "date"}
    assert _step_signature(step_a) != _step_signature(step_b)


def test_step_signature_use_tool_handles_unhashable_args():
    # Tool args can contain lists (e.g. x_values/y_values for a
    # regression tool) -- frozenset(dict.items()), used for the other
    # step types, would crash on these. This confirms the JSON-based
    # signature handles it without error.
    step = {"step": "use_tool", "tool_name": "linear_regression",
            "args": {"x_values": [1, 2, 3], "y_values": [4, 5, 6]}}
    signature = _step_signature(step)  # must not raise
    assert signature is not None


def test_step_signature_use_tool_ignores_arg_key_order():
    step_a = {"step": "use_tool", "tool_name": "linear_regression", "args": {"x_values": [1], "y_values": [2]}}
    step_b = {"step": "use_tool", "tool_name": "linear_regression", "args": {"y_values": [2], "x_values": [1]}}
    assert _step_signature(step_a) == _step_signature(step_b)


def test_detect_asymmetry_none_when_only_one_sibling():
    gathered = [
        {"step": "get_field", "object_type": "Transaction", "object_id": 1,
         "field_name": "amount", "result": 10},
    ]
    assert _detect_asymmetry(gathered) is None


def test_detect_asymmetry_none_when_fields_match():
    gathered = [
        {"step": "get_field", "object_type": "Transaction", "object_id": 1,
         "field_name": "amount", "result": 10},
        {"step": "get_field", "object_type": "Transaction", "object_id": 2,
         "field_name": "amount", "result": 20},
    ]
    assert _detect_asymmetry(gathered) is None


def test_detect_asymmetry_found_when_fields_differ():
    gathered = [
        {"step": "get_field", "object_type": "Transaction", "object_id": 1,
         "field_name": "amount", "result": 10},
        {"step": "get_field", "object_type": "Transaction", "object_id": 1,
         "field_name": "date", "result": "2026-01-01"},
        {"step": "get_field", "object_type": "Transaction", "object_id": 2,
         "field_name": "amount", "result": 20},
    ]
    assert _detect_asymmetry(gathered) is not None


def test_detect_asymmetry_ignores_link_results():
    gathered = [
        {"step": "get_field", "object_type": "Customer", "object_id": "c1",
         "field_name": "transactions", "result": [1, 2]},
    ]
    assert _detect_asymmetry(gathered) is None
