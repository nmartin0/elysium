"""
Tests for the pure-logic helper functions inside core/agent/agentic_loop.py --
no LLM, no I/O. Covers duplicate/asymmetry detection AND
AgentLoop.filter_real_data() -- all genuinely pure functions of their
arguments only, none needing instance state.
"""

from core.agent.agentic_loop import AgentLoop, _step_signature, _detect_asymmetry


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


def test_filter_real_data_strips_bookkeeping_entries():
    gathered = [
        {"step": "get_field", "object_type": "T", "object_id": 1, "field_name": "amount", "result": 10},
        {"step": "rejected_duplicate", "note": "..."},
        {"step": "completeness_check", "note": "..."},
        {"step": "rejected_invalid_step", "note": "..."},
    ]
    real_data = AgentLoop.filter_real_data(gathered)
    assert real_data == [{"step": "get_field", "object_type": "T", "object_id": 1, "field_name": "amount", "result": 10}]


def test_filter_real_data_strips_denied_or_null_field_reads():
    # THE hallucination-prevention proof: a denied get_field() -- same
    # None a genuinely-null database value would produce, deliberately
    # indistinguishable (uniform denial) -- must be COMPLETELY ABSENT
    # from what reaches synthesis, not present-as-None. A None left in
    # place would rely entirely on the model correctly interpreting it
    # as "omit this," rather than the model having no way to even know
    # the question was asked.
    gathered = [
        {"step": "get_field", "object_type": "Customer", "object_id": "c1",
         "field_name": "email", "result": None},  # denied OR genuinely null -- either way, excluded
        {"step": "get_field", "object_type": "Customer", "object_id": "c1",
         "field_name": "name", "result": "Ada Okafor"},  # a real value -- kept
    ]
    real_data = AgentLoop.filter_real_data(gathered)
    assert real_data == [
        {"step": "get_field", "object_type": "Customer", "object_id": "c1",
         "field_name": "name", "result": "Ada Okafor"},
    ]


def test_filter_real_data_keeps_empty_list_results():
    # search_object() denials/no-matches are empty LISTS, never bare
    # None -- this must NOT be swept up by the None-filtering above.
    # An empty list is real, legitimate information ("nothing matched"),
    # distinct from "this specific field was withheld."
    gathered = [
        {"step": "search_object", "object_type": "Customer", "filter": {"customer_id": "x"}, "result": []},
    ]
    real_data = AgentLoop.filter_real_data(gathered)
    assert real_data == gathered
