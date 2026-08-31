"""
Tests for core/deployment_loader.py's validate_identifier_types() --
catches YAML's own implicit type coercion (the "Norway problem":
unquoted no/yes/on/off/true/false becoming a real bool; an unquoted
date-like value becoming a real datetime.date; a leading-zero numeral
becoming octal) turning what an admin plainly intended as a string
identifier into something else entirely, BEFORE core/ontology/
action_types.py's validate_action_types() or core/intermediate_layer/
policy_validation.py's validate_roles() -- both of which assume every
name they compare is already a genuine string -- ever run.

Deliberately tests validate_identifier_types() directly, in isolation,
matching the same discipline tests/unit/test_action_types_validation.py
and tests/unit/test_policy_validation.py already use for their own
sibling validators.
"""

import pytest

from core.deployment_loader import validate_identifier_types


def _schema(object_types=None, action_types=None):
    schema = {"object_types": object_types or {}}
    if action_types is not None:
        schema["action_types"] = action_types
    return schema


def _policy(roles=None, users=None):
    policy = {"roles": roles or {}}
    if users is not None:
        policy["users"] = users
    return policy


def test_a_normal_valid_schema_and_policy_pass():
    schema = _schema({"Widget": {"id_field": "widget_id", "security": {"field": "region"},
                                  "fields": {"region": {}, "name": {}}}})
    policy = _policy({"viewer": {"allowed_actions": ["read:Widget"]}}, {"alice": {"role": "viewer"}})
    validate_identifier_types(schema, policy)  # does not raise


def test_object_type_name_coerced_to_bool_is_rejected():
    schema = _schema({True: {"fields": {}}})
    with pytest.raises(ValueError, match="An object_type name.*not a string"):
        validate_identifier_types(schema, _policy())


def test_id_field_coerced_to_a_non_string_is_rejected():
    schema = _schema({"Widget": {"id_field": True, "fields": {}}})
    with pytest.raises(ValueError, match="'Widget'.*id_field.*not a string"):
        validate_identifier_types(schema, _policy())


def test_security_field_coerced_to_a_non_string_is_rejected():
    schema = _schema({"Widget": {"security": {"field": False}, "fields": {}}})
    with pytest.raises(ValueError, match="'Widget'.*security.field.*not a string"):
        validate_identifier_types(schema, _policy())


def test_field_name_coerced_to_a_non_string_is_rejected():
    schema = _schema({"Widget": {"fields": {2024: {}}}})
    with pytest.raises(ValueError, match="field name on 'Widget'.*not a string"):
        validate_identifier_types(schema, _policy())


def test_action_type_name_coerced_to_a_non_string_is_rejected():
    schema = _schema({}, {False: {"parameters": {}}})
    with pytest.raises(ValueError, match="An action_type name.*not a string"):
        validate_identifier_types(schema, _policy())


def test_parameter_name_coerced_to_a_non_string_is_rejected():
    schema = _schema({}, {"RenameWidget": {"parameters": {True: {}}}})
    with pytest.raises(ValueError, match="parameter name on 'RenameWidget'.*not a string"):
        validate_identifier_types(schema, _policy())


def test_affected_object_types_entry_coerced_to_a_non_string_is_rejected():
    schema = _schema({}, {"RenameWidget": {"affected_object_types": [True]}})
    with pytest.raises(ValueError, match="affected_object_types entry on 'RenameWidget'.*not a string"):
        validate_identifier_types(schema, _policy())


def test_sub_write_object_type_coerced_to_a_non_string_is_rejected():
    schema = _schema({}, {"RenameWidget": {"sub_writes": [{"object_type": False}]}})
    with pytest.raises(ValueError, match="sub_writes\\[0\\].object_type.*not a string"):
        validate_identifier_types(schema, _policy())


def test_role_name_coerced_to_bool_is_rejected():
    # THE real, empirically-found case that motivated this whole
    # module: a role literally named "no" resolves to the Python
    # boolean False, not the string "no" -- see this project's own
    # commit history / AI-notes for the direct, confirmed proof.
    with pytest.raises(ValueError, match="A role name.*not a string"):
        validate_identifier_types(_schema(), _policy({False: {"allowed_actions": []}}))


def test_grant_coerced_to_a_non_string_is_rejected():
    with pytest.raises(ValueError, match="grant in role 'viewer'.*not a string"):
        validate_identifier_types(_schema(), _policy({"viewer": {"allowed_actions": [True]}}))


def test_user_id_coerced_to_a_non_string_is_rejected():
    with pytest.raises(ValueError, match="user_id.*not a string"):
        validate_identifier_types(_schema(), _policy(users={False: {"role": "viewer"}}))


def test_missing_optional_sections_do_not_raise():
    # affected_object_types/sub_writes/parameters/users are all
    # genuinely optional at various points -- must not crash trying
    # to iterate something that's simply absent.
    schema = _schema({}, {"BareAction": {}})
    validate_identifier_types(schema, _policy({"viewer": {}}))  # does not raise


def test_explicitly_null_optional_sections_do_not_raise():
    # A YAML key present but with nothing after it (e.g. "sub_writes:"
    # with no value) parses as None, not a missing key or an empty
    # list/dict -- a plain .get(key, []) would NOT catch this, since
    # the key genuinely exists; must not crash either way.
    schema = _schema({}, {"BareAction": {"affected_object_types": None, "sub_writes": None}})
    validate_identifier_types(schema, _policy({"viewer": {"allowed_actions": None}}))  # does not raise
