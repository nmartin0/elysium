"""
Tests for core/intermediate_layer/policy_validation.py's validate_roles()
-- schema-load-time validation for policy.yaml's role grants. See that
module's own docstring for the full reasoning: authorize() itself does
a bare exact-string match with no existence-checking of its own, so a
typo'd grant would otherwise never fail loudly anywhere, just silently
never match anything.

OBJECT_TYPES/ACTION_TYPES here are small, deliberately synthetic
fixtures -- this file tests the VALIDATOR itself in isolation, matching
the same discipline tests/unit/test_action_types_validation.py already
uses for the sibling ontology_schema.yaml validator.
"""

import pytest

from core.intermediate_layer.policy_validation import validate_roles

OBJECT_TYPES = {
    "Widget": {"id_field": "widget_id", "fields": {"name": {"type": "data"}}},
}
ACTION_TYPES = {
    "RenameWidget": {},  # only the NAME is checked here, not its own shape
}
ENABLED_TOOLS = ["linear_regression"]


def _role(*grants):
    return {"editor": {"allowed_actions": list(grants)}}


def test_manage_users_is_always_valid():
    validate_roles(_role("manage:users"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_execute_a_real_action_type_is_valid():
    validate_roles(_role("execute:RenameWidget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_execute_an_unknown_action_type_is_rejected():
    with pytest.raises(ValueError, match="unknown action type 'RenmaeWidget'"):
        validate_roles(_role("execute:RenmaeWidget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_tool_a_real_enabled_tool_is_valid():
    validate_roles(_role("tool:linear_regression"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_tool_not_in_enabled_tools_is_rejected():
    with pytest.raises(ValueError, match="tool 'unknown_tool'"):
        validate_roles(_role("tool:unknown_tool"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_read_type_level_grant_for_a_real_type_is_valid():
    validate_roles(_role("read:Widget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_read_type_level_grant_for_unknown_type_is_rejected():
    with pytest.raises(ValueError, match="unknown object type 'Wigdet'"):
        validate_roles(_role("read:Wigdet"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_read_field_level_grant_for_a_real_field_is_valid():
    validate_roles(_role("read:Widget.name"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_read_field_level_grant_for_the_id_field_is_valid():
    # id_field is a real, addressable field even though it isn't
    # listed under the type's own "fields" -- must not be rejected.
    validate_roles(_role("read:Widget.widget_id"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_read_field_level_grant_for_unknown_field_is_rejected():
    with pytest.raises(ValueError, match="unknown field 'nmae'"):
        validate_roles(_role("read:Widget.nmae"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_read_field_level_grant_for_unknown_type_is_rejected():
    with pytest.raises(ValueError, match="unknown object type 'Wigdet'"):
        validate_roles(_role("read:Wigdet.name"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_write_field_level_grant_for_a_real_field_is_valid():
    validate_roles(_role("write:Widget.name"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_write_field_level_grant_for_unknown_field_is_rejected():
    with pytest.raises(ValueError, match="unknown field 'nmae'"):
        validate_roles(_role("write:Widget.nmae"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_write_type_level_grant_with_no_field_is_rejected():
    # write: is only ever constructed as write:<Type>.<field> -- a
    # bare write:<Type> can never match a real authorize() call.
    with pytest.raises(ValueError, match="never constructed anywhere"):
        validate_roles(_role("write:Widget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_completely_unrecognized_grant_pattern_is_rejected():
    with pytest.raises(ValueError, match="doesn't match any recognized pattern"):
        validate_roles(_role("delete:Widget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_a_valid_grant_does_not_hide_an_invalid_one_in_the_same_role():
    roles = {"editor": {"allowed_actions": ["read:Widget", "execute:TotallyFakeAction"]}}
    with pytest.raises(ValueError, match="unknown action type 'TotallyFakeAction'"):
        validate_roles(roles, OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_one_invalid_role_does_not_hide_behind_a_valid_sibling():
    roles = {
        "fine_role": {"allowed_actions": ["read:Widget"]},
        "broken_role": {"allowed_actions": ["read:Wigdet"]},
    }
    with pytest.raises(ValueError, match="unknown object type 'Wigdet'"):
        validate_roles(roles, OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_a_role_with_no_allowed_actions_at_all_is_fine():
    validate_roles({"empty_role": {}}, OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise
