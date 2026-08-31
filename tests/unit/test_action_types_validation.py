"""
Tests for core/ontology/action_types.py's validate_action_types() --
schema-load-time validation for action_types using the newer
sub_writes shape. An action_type still using the OLDER, flat shape
(object_type/operation/mutations) is deliberately, completely
untouched -- proven directly below, not just assumed.

OBJECT_TYPES here is a small, deliberately synthetic schema (Widget/
Gadget/Gizmo) -- this file tests the VALIDATOR itself in isolation,
not any real business action, matching this project's own decision
not to author a real multi-object action_type yet (see this
increment's own design discussion: the sub_writes mechanism gets
built and proven correct on its own merits first, without yet
exercising the model-facing object_id/hint-mechanism question that
depends on a real one existing).
"""

import pytest

from core.ontology.action_types import MAX_SUB_WRITES, validate_action_types

OBJECT_TYPES = {
    "Widget": {"fields": {"name": {"type": "data"}}},
    "Gadget": {"fields": {"name": {"type": "data"}}},
    "Gizmo": {"fields": {"name": {"type": "data"}}},
}


def _obj_ref_param(object_type: str) -> dict:
    return {"type": "object_reference", "object_type": object_type, "required": True}


def _sub_write(object_type="Widget", object_id="parameter.widget_id", operation="update",
                mutations=None):
    # mutations if mutations is not None else [...] -- NOT `mutations
    # or [...]`, which would silently treat an explicitly-passed EMPTY
    # list the same as "not provided at all" (an empty list is falsy
    # in Python), defeating the one test this helper exists to support
    # in the first place: proving an explicitly empty mutations list
    # is correctly rejected.
    default_mutations = [{"set": {"property": "name", "value": "parameter.new_name"}}]
    return {
        "object_type": object_type,
        "object_id": object_id,
        "operation": operation,
        "mutations": mutations if mutations is not None else default_mutations,
    }


def test_old_flat_shape_action_type_is_completely_untouched():
    # No "sub_writes" key at all -- and otherwise missing everything
    # this module would require of a sub_writes-shaped action, proving
    # this branch is genuinely skipped entirely, not just lenient.
    action_types = {"RenameWidget": {"object_type": "Widget", "operation": "update"}}
    validate_action_types(action_types, OBJECT_TYPES)  # does not raise


def test_valid_two_object_sub_writes_action_passes():
    action_types = {
        "SwapNames": {
            "affected_object_types": ["Widget", "Gadget"],
            "parameters": {"widget_id": _obj_ref_param("Widget"), "gadget_id": _obj_ref_param("Gadget")},
            "sub_writes": [
                _sub_write("Widget", "parameter.widget_id"),
                _sub_write("Gadget", "parameter.gadget_id"),
            ],
        }
    }
    validate_action_types(action_types, OBJECT_TYPES)  # does not raise


def test_sub_writes_must_be_a_non_empty_list():
    action_types = {"Bad": {"affected_object_types": ["Widget"], "sub_writes": []}}
    with pytest.raises(ValueError, match="non-empty list"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_writes_exceeding_the_cap_is_rejected():
    action_types = {
        "TooMany": {
            "affected_object_types": ["Widget"],
            "parameters": {f"id_{i}": _obj_ref_param("Widget") for i in range(MAX_SUB_WRITES + 1)},
            "sub_writes": [_sub_write("Widget", f"parameter.id_{i}") for i in range(MAX_SUB_WRITES + 1)],
        }
    }
    with pytest.raises(ValueError, match=f"exceeds the maximum of {MAX_SUB_WRITES}"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_writes_at_exactly_the_cap_is_allowed():
    action_types = {
        "ExactlyAtCap": {
            "affected_object_types": ["Widget"],
            "parameters": {f"id_{i}": _obj_ref_param("Widget") for i in range(MAX_SUB_WRITES)},
            "sub_writes": [_sub_write("Widget", f"parameter.id_{i}") for i in range(MAX_SUB_WRITES)],
        }
    }
    validate_action_types(action_types, OBJECT_TYPES)  # does not raise


def test_affected_object_types_required_when_sub_writes_used():
    action_types = {"Bad": {"sub_writes": [_sub_write()]}}
    with pytest.raises(ValueError, match="affected_object_types is required"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_affected_object_types_naming_unknown_type_is_rejected():
    action_types = {
        "Bad": {"affected_object_types": ["Sprocket"], "sub_writes": [_sub_write("Widget")]}
    }
    with pytest.raises(ValueError, match="unknown object type"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_write_missing_a_required_key_is_rejected():
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "sub_writes": [{"object_type": "Widget", "operation": "update"}],  # no object_id, no mutations
        }
    }
    with pytest.raises(ValueError, match="missing required key"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_write_referencing_unknown_object_type_is_rejected():
    action_types = {
        "Bad": {"affected_object_types": ["Widget"], "sub_writes": [_sub_write("Sprocket")]}
    }
    with pytest.raises(ValueError, match="unknown object type"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_write_operation_must_be_create_or_update():
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "sub_writes": [_sub_write(operation="delete")],
        }
    }
    with pytest.raises(ValueError, match="'create' or 'update'"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_write_mutations_must_be_a_non_empty_list():
    action_types = {
        "Bad": {"affected_object_types": ["Widget"], "sub_writes": [_sub_write(mutations=[])]}
    }
    with pytest.raises(ValueError, match="mutations must be a non-empty list"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_duplicate_identical_object_reference_across_sub_writes_is_rejected():
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "parameters": {"widget_id": _obj_ref_param("Widget")},
            "sub_writes": [
                _sub_write("Widget", "parameter.widget_id"),
                _sub_write("Widget", "parameter.widget_id"),  # literally identical reference
            ],
        }
    }
    with pytest.raises(ValueError, match="both reference the IDENTICAL"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_different_expressions_for_the_same_type_are_not_flagged_as_duplicates():
    # Structural check only -- see this module's own docstring for why
    # two DIFFERENT expressions (which COULD still resolve to the same
    # real id once real parameters arrive) are deliberately NOT
    # rejected here; that full check belongs at propose_action() time.
    action_types = {
        "Fine": {
            "affected_object_types": ["Widget"],
            "parameters": {"from_widget_id": _obj_ref_param("Widget"), "to_widget_id": _obj_ref_param("Widget")},
            "sub_writes": [
                _sub_write("Widget", "parameter.from_widget_id"),
                _sub_write("Widget", "parameter.to_widget_id"),
            ],
        }
    }
    validate_action_types(action_types, OBJECT_TYPES)  # does not raise


def test_affected_object_types_under_declaration_is_rejected():
    # Gadget is actually referenced but never declared.
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "parameters": {"widget_id": _obj_ref_param("Widget"), "gadget_id": _obj_ref_param("Gadget")},
            "sub_writes": [_sub_write("Widget", "parameter.widget_id"), _sub_write("Gadget", "parameter.gadget_id")],
        }
    }
    with pytest.raises(ValueError, match="used but undeclared"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_affected_object_types_over_declaration_is_rejected():
    # Gizmo is declared but no sub_write actually touches it.
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget", "Gizmo"],
            "parameters": {"widget_id": _obj_ref_param("Widget")},
            "sub_writes": [_sub_write("Widget", "parameter.widget_id")],
        }
    }
    with pytest.raises(ValueError, match="declared but unused"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_one_invalid_action_type_does_not_hide_behind_a_valid_sibling():
    # Proves validation is per-action-type, not short-circuited or
    # merged across the whole dict -- a totally fine, older-shape
    # action_type sitting right next to a broken new-shape one must
    # still surface the SECOND one's own real error.
    action_types = {
        "FineOldShape": {"object_type": "Widget", "operation": "update"},
        "BrokenNewShape": {"affected_object_types": ["Widget"], "sub_writes": []},
    }
    with pytest.raises(ValueError, match="non-empty list"):
        validate_action_types(action_types, OBJECT_TYPES)


# --- object_reference parameters -------------------------------------------

def test_object_reference_parameter_without_object_type_is_rejected():
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "parameters": {"widget_id": {"type": "object_reference", "required": True}},  # no object_type
            "sub_writes": [_sub_write("Widget", "parameter.widget_id")],
        }
    }
    with pytest.raises(ValueError, match="no object_type of its own"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_object_reference_parameter_naming_unknown_type_is_rejected():
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "parameters": {"widget_id": _obj_ref_param("Sprocket")},
            "sub_writes": [_sub_write("Widget", "parameter.widget_id")],
        }
    }
    with pytest.raises(ValueError, match="unknown object type"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_object_reference_parameter_not_used_by_any_sub_write_is_still_validated():
    # A parameter can legitimately be an object reference used only in
    # a mutation value or submission_criteria, never as a sub_write's
    # own object_id -- it still deserves the same object_type scrutiny.
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "parameters": {
                "widget_id": _obj_ref_param("Widget"),
                "notify_gadget_id": _obj_ref_param("Sprocket"),  # unused as an object_id, still checked
            },
            "sub_writes": [_sub_write("Widget", "parameter.widget_id")],
        }
    }
    with pytest.raises(ValueError, match="unknown object type"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_write_object_id_referencing_undeclared_parameter_is_rejected():
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "sub_writes": [_sub_write("Widget", "parameter.nonexistent_id")],
        }
    }
    with pytest.raises(ValueError, match="not declared in this action's own parameters"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_write_object_id_referencing_non_object_reference_parameter_is_rejected():
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "parameters": {"widget_id": {"type": "string", "required": True}},  # wrong type
            "sub_writes": [_sub_write("Widget", "parameter.widget_id")],
        }
    }
    with pytest.raises(ValueError, match="must be declared type 'object_reference'"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_write_object_id_referencing_mismatched_object_type_is_rejected():
    action_types = {
        "Bad": {
            "affected_object_types": ["Widget"],
            "parameters": {"gadget_id": _obj_ref_param("Gadget")},  # wrong type for this sub_write
            "sub_writes": [_sub_write("Widget", "parameter.gadget_id")],
        }
    }
    with pytest.raises(ValueError, match="these must match"):
        validate_action_types(action_types, OBJECT_TYPES)


def test_sub_write_object_id_as_literal_needs_no_parameter_declaration():
    # object_id uses the SAME resolution vocabulary as mutation values
    # (literal, parameter.<name>, user.security_value) -- a literal
    # object_id is structurally fine with nothing further to check.
    action_types = {
        "Fine": {
            "affected_object_types": ["Widget"],
            "sub_writes": [_sub_write("Widget", "widget_042")],
        }
    }
    validate_action_types(action_types, OBJECT_TYPES)  # does not raise


def test_sub_write_object_id_as_user_security_value_needs_no_parameter_declaration():
    action_types = {
        "Fine": {
            "affected_object_types": ["Widget"],
            "sub_writes": [_sub_write("Widget", "user.security_value")],
        }
    }
    validate_action_types(action_types, OBJECT_TYPES)  # does not raise
