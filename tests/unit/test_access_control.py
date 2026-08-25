"""
Tests for core/intermediate_layer/access_control.py's check_access() --
the single canonical enforcement point. Four scenarios, matching the
"MAC-allow, MAC-deny, RBAC-allow, RBAC-deny" discipline established for
every access surface in this project (see tests/unit/test_mediator.py
and test_write_mediator.py for the same pattern applied elsewhere).
"""

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.intermediate_layer.access_control import check_access
from core.ontology.mediator import DataMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
    "carol": {"org_id": "org-a"},  # no role
}

TEST_ROLES = {
    "reader": {"allowed_actions": ["read:Author"]},
}


@pytest.fixture
def mediator(test_db_path, test_schema) -> DataMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["silo"] for object_type, type_def in test_schema.items()}
    return DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_USERS, TEST_ROLES, "org_id")


def test_both_gates_pass(mediator):
    assert check_access(mediator, TEST_USERS, TEST_ROLES, "org_id", "alice", "Author", "auth_001", "read:Author") is True


def test_mac_fails_rbac_passes(mediator):
    # bob has the role, but auth_001 is a different org.
    assert check_access(mediator, TEST_USERS, TEST_ROLES, "org_id", "bob", "Author", "auth_001", "read:Author") is False


def test_mac_passes_rbac_fails(mediator):
    # carol is the right org, but has no role at all.
    assert check_access(mediator, TEST_USERS, TEST_ROLES, "org_id", "carol", "Author", "auth_001", "read:Author") is False


def test_both_gates_fail(mediator):
    # A user who exists nowhere in TEST_USERS at all.
    assert check_access(mediator, TEST_USERS, TEST_ROLES, "org_id", "nobody", "Author", "auth_001", "read:Author") is False


def test_unknown_action_denied_even_with_valid_role(mediator):
    # alice has read:Author, not write:Author.
    assert check_access(mediator, TEST_USERS, TEST_ROLES, "org_id", "alice", "Author", "auth_001", "write:Author") is False
