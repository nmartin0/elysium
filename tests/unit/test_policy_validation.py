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

from core.intermediate_layer.policy_validation import validate_role_coherence, validate_roles

OBJECT_TYPES = {
    "Widget": {"id_field": "widget_id", "fields": {"name": {"type": "data"}}},
}
ACTION_TYPES = {
    "RenameWidget": {},  # only the NAME is checked here, not its own shape
}
ENABLED_TOOLS = ["linear_regression"]


def _role(*grants):
    """A role holding exactly these grants.

    Field grants get their TYPE grant added automatically, because a
    field grant without one is now refused -- a role cannot read a
    field of a type it cannot see. These tests are about whether a
    field grant NAMES something real, and each would otherwise fail on
    a rule it is not testing.

    Tests for the coherence rule itself build their roles directly, so
    this helper cannot mask it.
    """
    grants = list(grants)
    implied = [
        f"read:{grant.split(':', 1)[1].split('.', 1)[0]}"
        for grant in grants
        if grant.startswith(("read:", "discover:")) and "." in grant.split(":", 1)[1]
    ]
    return {"editor": {"allowed_actions": grants + [g for g in implied if g not in grants]}}


def test_manage_users_is_always_valid():
    validate_roles(_role("manage:users"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_discover_action_types_is_always_valid():
    # Same exact-literal shape as manage:users above -- a single,
    # blanket grant, nothing further to reference or validate.
    validate_roles(_role("discover:action_types"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_execute_a_real_action_type_is_valid():
    validate_roles(_role("execute:RenameWidget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_execute_an_unknown_action_type_is_rejected():
    with pytest.raises(ValueError, match="unknown action type 'RenmaeWidget'"):
        validate_roles(_role("execute:RenmaeWidget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_tool_a_real_enabled_tool_is_valid():
    validate_roles(_role("tool:linear_regression"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_tool_not_in_enabled_tools_is_rejected():
    with pytest.raises(ValueError, match="tool not in config.yaml"):
        validate_roles(_role("tool:unknown_tool"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_read_type_level_grant_for_a_real_type_is_valid():
    validate_roles(_role("read:Widget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


def test_read_type_level_grant_for_unknown_type_is_rejected():
    with pytest.raises(ValueError, match="unknown type 'Wigdet'"):
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
    with pytest.raises(ValueError, match="unknown type 'Wigdet'"):
        validate_roles(_role("read:Wigdet.name"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_a_write_grant_is_rejected_outright():
    """`write:<Type>.<field>` was accepted here and checked by no
    authorize() call anywhere -- writes are authorized per action type,
    so a policy granting it validated cleanly and permitted nothing.

    Rejected now rather than accepted as a no-op: a grant that reads as
    a permission and grants nothing is worse than one that fails.
    """
    with pytest.raises(ValueError, match="not enforced anywhere"):
        validate_roles(_role("write:Widget.name"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_the_write_rejection_names_the_real_alternative():
    # Someone reaching for write: wants to permit a write. The message
    # has to say how that is actually done, or they will simply try
    # another spelling of the same wrong thing.
    with pytest.raises(ValueError, match="execute:<ActionType>"):
        validate_roles(_role("write:Widget.name"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_a_write_grant_is_rejected_whatever_it_names():
    # Including one whose type and field are perfectly real -- the
    # prefix is the problem, not what follows it.
    for grant in ("write:Widget", "write:Widget.name", "write:Nonexistent.field"):
        with pytest.raises(ValueError, match="not enforced anywhere"):
            validate_roles(_role(grant), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


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
    with pytest.raises(ValueError, match="unknown type 'Wigdet'"):
        validate_roles(roles, OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_a_role_with_no_allowed_actions_at_all_is_fine():
    validate_roles({"empty_role": {}}, OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)  # does not raise


# --- the coherence rule: a field grant needs its type -----------------
#
# Grants were independent strings, so `read:Customer.email` could be
# held WITHOUT any grant on Customer -- a role authorised to read a
# field of a type it cannot even discover. Verified against authorize()
# before the rule existed: True for the field, False for the type.
#
# Nothing enforced it because nothing looked at two grants together;
# every other check in this module reads one string at a time.

def test_a_field_grant_without_its_type_is_refused():
    roles = {"editor": {"allowed_actions": ["read:Widget.name"]}}

    with pytest.raises(ValueError, match="no grant on 'Widget'"):
        validate_role_coherence(roles)


def test_a_read_grant_on_the_type_satisfies_it():
    roles = {"editor": {"allowed_actions": ["read:Widget", "read:Widget.name"]}}

    validate_role_coherence(roles)


def test_a_DISCOVER_grant_on_the_type_satisfies_it_too():
    # The field needs the type to be VISIBLE, not readable. A role that
    # may know Widget exists and may read one of its fields is
    # coherent -- and is exactly the shape the ladder exists to allow.
    roles = {"editor": {"allowed_actions": ["discover:Widget", "read:Widget.name"]}}

    validate_role_coherence(roles)


def test_a_discover_field_grant_needs_its_type_as_well():
    roles = {"editor": {"allowed_actions": ["discover:Widget.name"]}}

    with pytest.raises(ValueError, match="no grant on 'Widget'"):
        validate_role_coherence(roles)


def test_a_bare_type_grant_is_unaffected():
    # THE CONTROL. The overwhelmingly common shape, and a rule that
    # demanded something of it would break every deployment.
    validate_roles(_role("read:Widget"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)


def test_discover_on_a_type_that_does_not_exist_is_refused():
    # The new verb names the same things read: does, so a typo in it is
    # the same mistake and must fail the same way.
    with pytest.raises(ValueError, match="unknown type"):
        validate_roles(_role("discover:Wigdet"), OBJECT_TYPES, ACTION_TYPES, ENABLED_TOOLS)
