"""
Tests for the pure-logic helper functions inside core/agent/loop.py --
no LLM, no I/O, just the duplicate/asymmetry detection logic itself.
"""

from core.agent.loop import _step_signature, _detect_asymmetry


def test_step_signature_search_object_is_order_independent():
    step_a = {"step": "search_object", "object_type": "Customer", "filter": {"a": 1, "b": 2}}
    step_b = {"step": "search_object", "object_type": "Customer", "filter": {"b": 2, "a": 1}}
    assert _step_signature(step_a) == _step_signature(step_b)


def test_step_signature_get_field_distinguishes_different_fields():
    step_a = {"step": "get_field", "object_type": "T", "object_id": 1, "field_name": "amount"}
    step_b = {"step": "get_field", "object_type": "T", "object_id": 1, "field_name": "date"}
    assert _step_signature(step_a) != _step_signature(step_b)


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
    # A link field's result is a LIST of IDs -- not a data field, must
    # not be counted toward asymmetry detection.
    gathered = [
        {"step": "get_field", "object_type": "Customer", "object_id": "c1",
         "field_name": "transactions", "result": [1, 2]},
    ]
    assert _detect_asymmetry(gathered) is None
