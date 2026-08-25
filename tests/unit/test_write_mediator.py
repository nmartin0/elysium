"""
Tests for core/ontology/write_mediator.py -- the highest-stakes new code
in this project, so this gets real, dedicated coverage. WriteMediator
takes a pre-resolved UserRecord now, not a raw user_id.

Field-level write RBAC: every field in `changes` needs its own
write:Type.field grant, all-or-nothing. create:Type is a separate
action from any field grant.

alice: org-a, role=editor      -- read/write:Author.name, create:Author
bob:   org-b, role=editor      -- different org -- MAC boundary test
carol: org-a, NO role          -- same org as alice -- RBAC-only denial test
dave:  org-a, role=name_only   -- write:Author.name but NOT write:Author.org_id
"""

import pytest
from dataclasses import FrozenInstanceError

from adapters.sqlite_adapter import SQLiteAdapter
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_mediator import WriteMediator, PendingWrite

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "editor"},
    "bob": {"org_id": "org-b", "role": "editor"},
    "carol": {"org_id": "org-a"},  # deliberately no role
    "dave": {"org_id": "org-a", "role": "name_only"},
}

TEST_ROLES = {
    "editor": {"allowed_actions": [
        "read:Author", "read:Author.name", "write:Author.name", "create:Author",
    ]},
    "name_only": {"allowed_actions": ["read:Author", "write:Author.name"]},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def wm(test_db_path, test_schema) -> WriteMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["silo"] for object_type, type_def in test_schema.items()}
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES)
    return WriteMediator(mediator, TEST_ROLES)


def test_propose_write_denied_without_role_rbac(wm):
    with pytest.raises(PermissionError):
        wm.propose_write(_record("carol"), "Author", "auth_001", "update", {"name": "Someone Else"})


def test_propose_write_denied_cross_org_even_with_role_granted_mac(wm):
    with pytest.raises(PermissionError):
        wm.propose_write(_record("bob"), "Author", "auth_001", "update", {"name": "Hacked"})


def test_propose_write_denied_for_ungranted_field_even_with_other_fields_granted(wm):
    with pytest.raises(PermissionError):
        wm.propose_write(_record("dave"), "Author", "auth_001", "update", {"org_id": "org-hacked"})


def test_propose_write_multi_field_is_all_or_nothing(wm):
    with pytest.raises(PermissionError):
        wm.propose_write(_record("dave"), "Author", "auth_001", "update", {"name": "New Name", "org_id": "sneaky"})


def test_propose_create_denied_without_create_action_even_with_field_grant(wm):
    with pytest.raises(PermissionError):
        wm.propose_write(_record("dave"), "Author", None, "create", {"name": "New Author"})


def test_propose_write_succeeds_for_own_org_object(wm):
    pending = wm.propose_write(_record("alice"), "Author", "auth_001", "update", {"name": "Ada L."})
    assert pending.object_type == "Author"
    assert pending.user_id == "alice"
    assert pending.changes == {"name": "Ada L."}


def test_pending_write_is_immutable(wm):
    pending = wm.propose_write(_record("alice"), "Author", "auth_001", "update", {"name": "Ada L."})
    with pytest.raises(FrozenInstanceError):
        pending.changes = {"name": "TAMPERED"}


def test_rejected_write_does_not_touch_database(wm):
    pending = wm.propose_write(_record("alice"), "Author", "auth_001", "update", {"name": "Should Not Apply"})
    result = wm.confirm_and_execute(pending, approved=False)
    assert result is None

    real_value = wm.mediator.get_field(_record("alice"), "Author", "auth_001", "name")
    assert real_value == "Ada Lovelace"


def test_approved_write_actually_updates_the_database(wm):
    pending = wm.propose_write(_record("alice"), "Author", "auth_001", "update", {"name": "Ada, Countess of Lovelace"})
    result = wm.confirm_and_execute(pending, approved=True)
    assert result == {"status": "written", "object_id": "auth_001"}

    real_value = wm.mediator.get_field(_record("alice"), "Author", "auth_001", "name")
    assert real_value == "Ada, Countess of Lovelace"
