"""
Tests for core/intermediate_layer/access_control.py's check_access() --
the single canonical enforcement point. Takes a pre-resolved UserRecord
now, not a raw user_id + users dict + security_attribute -- and no
longer needs security_attribute at all, since UserRecord already
carries the resolved MAC value (a real reduction, not a relocation).

Four scenarios, matching the "MAC-allow, MAC-deny, RBAC-allow,
RBAC-deny" discipline established for every access surface in this
project.
"""

import pytest

from adapters.sqlite_adapter import SQLiteWriteAdapter
from core.intermediate_layer.access_control import check_access
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
    "carol": {"org_id": "org-a"},  # no role
}

TEST_ROLES = {
    "reader": {"allowed_actions": ["read:Author"]},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def mediator(test_db_path, test_schema) -> DataMediator:
    adapter = SQLiteWriteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    return DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES)


def test_both_gates_pass(mediator):
    assert check_access(mediator, _record("alice"), TEST_ROLES, "Author", "auth_001", "read:Author") is True


def test_mac_fails_rbac_passes(mediator):
    # bob has the role, but auth_001 is a different org.
    assert check_access(mediator, _record("bob"), TEST_ROLES, "Author", "auth_001", "read:Author") is False


def test_mac_passes_rbac_fails(mediator):
    # carol is the right org, but has no role at all.
    assert check_access(mediator, _record("carol"), TEST_ROLES, "Author", "auth_001", "read:Author") is False


def test_both_gates_fail(mediator):
    # A user who exists nowhere in TEST_USERS at all -- resolve_user_record
    # still returns a valid (empty) UserRecord, never crashes.
    assert check_access(mediator, _record("nobody"), TEST_ROLES, "Author", "auth_001", "read:Author") is False


def test_unknown_action_denied_even_with_valid_role(mediator):
    # alice has read:Author, not write:Author.
    assert check_access(mediator, _record("alice"), TEST_ROLES, "Author", "auth_001", "write:Author") is False
