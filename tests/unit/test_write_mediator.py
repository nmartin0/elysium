"""
Tests for core/ontology/write_mediator.py -- the highest-stakes new code
in this project, so this gets real, dedicated coverage rather than
relying only on ad-hoc verification. Uses the same isolated
test_db_path/test_schema fixtures as tests/unit/test_mediator.py.

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
    "name_only": {"allowed_actions": ["read:Author", "write:Author.name"]},  # no create:Author, no write:Author.org_id
}


@pytest.fixture
def wm(test_db_path, test_schema) -> WriteMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["silo"] for object_type, type_def in test_schema.items()}
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type,
                             TEST_USERS, TEST_ROLES, "org_id")
    return WriteMediator(mediator, TEST_USERS, TEST_ROLES, "org_id")


def test_propose_write_denied_without_role_rbac(wm):
    # carol has no role at all -- must be denied at the FIRST check
    # (authorize/RBAC), never even reaching the row-level (MAC) check.
    with pytest.raises(PermissionError):
        wm.propose_write("carol", "Author", "auth_001", "update", {"name": "Someone Else"})


def test_propose_write_denied_cross_org_even_with_role_granted_mac(wm):
    # bob HAS write:Author.name, but auth_001 belongs to org-a, not
    # org-b -- the row-level (MAC) check must still block this.
    with pytest.raises(PermissionError):
        wm.propose_write("bob", "Author", "auth_001", "update", {"name": "Hacked"})


def test_propose_write_denied_for_ungranted_field_even_with_other_fields_granted(wm):
    # dave has write:Author.name but NOT write:Author.org_id -- writing
    # ONLY org_id must be denied.
    with pytest.raises(PermissionError):
        wm.propose_write("dave", "Author", "auth_001", "update", {"org_id": "org-hacked"})


def test_propose_write_multi_field_is_all_or_nothing(wm):
    # dave has write:Author.name but not write:Author.org_id -- trying
    # to set BOTH in one write must deny the WHOLE thing, not just
    # silently apply the one field he does have.
    with pytest.raises(PermissionError):
        wm.propose_write("dave", "Author", "auth_001", "update", {"name": "New Name", "org_id": "sneaky"})


def test_propose_create_denied_without_create_action_even_with_field_grant(wm):
    # dave has write:Author.name but no create:Author -- must be denied.
    with pytest.raises(PermissionError):
        wm.propose_write("dave", "Author", None, "create", {"name": "New Author"})


def test_propose_write_succeeds_for_own_org_object(wm):
    pending = wm.propose_write("alice", "Author", "auth_001", "update", {"name": "Ada L."})
    assert pending.object_type == "Author"
    assert pending.user_id == "alice"
    assert pending.changes == {"name": "Ada L."}


def test_pending_write_is_immutable(wm):
    pending = wm.propose_write("alice", "Author", "auth_001", "update", {"name": "Ada L."})
    with pytest.raises(FrozenInstanceError):
        pending.changes = {"name": "TAMPERED"}


def test_rejected_write_does_not_touch_database(wm):
    pending = wm.propose_write("alice", "Author", "auth_001", "update", {"name": "Should Not Apply"})
    result = wm.confirm_and_execute(pending, approved=False)
    assert result is None

    real_value = wm.mediator.get_field("alice", "Author", "auth_001", "name")
    assert real_value == "Ada Lovelace"  # unchanged from conftest.py's seed data


def test_approved_write_actually_updates_the_database(wm):
    pending = wm.propose_write("alice", "Author", "auth_001", "update", {"name": "Ada, Countess of Lovelace"})
    result = wm.confirm_and_execute(pending, approved=True)
    assert result == {"status": "written", "object_id": "auth_001"}

    real_value = wm.mediator.get_field("alice", "Author", "auth_001", "name")
    assert real_value == "Ada, Countess of Lovelace"
