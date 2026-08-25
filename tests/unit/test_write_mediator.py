"""
Tests for core/ontology/write_mediator.py -- the highest-stakes new code
in this project, so this gets real, dedicated coverage rather than
relying only on ad-hoc verification. Uses the same isolated
test_db_path/test_schema fixtures as tests/unit/test_mediator.py.
"""

import pytest
from dataclasses import FrozenInstanceError

from adapters.sqlite_adapter import SQLiteAdapter
from core.ontology.mediator import DataMediator
from core.ontology.write_mediator import WriteMediator, PendingWrite

TEST_USERS = {
    "alice": {"org_id": "org-a", "allowed_actions": ["write:Author"]},
    "bob": {"org_id": "org-b", "allowed_actions": []},  # no write permission at all
}


@pytest.fixture
def wm(test_db_path, test_schema) -> WriteMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["silo"] for object_type, type_def in test_schema.items()}
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type)
    return WriteMediator(mediator, TEST_USERS, "org_id")


def test_propose_write_denied_without_allowed_action(wm):
    # bob has no allowed_actions at all -- must be denied at the FIRST
    # check (authorize), never even reaching the row-level check.
    with pytest.raises(PermissionError):
        wm.propose_write("bob", "Author", "auth_001", "update", {"name": "Someone Else"})


def test_propose_write_denied_cross_org_even_with_action_granted(wm):
    # alice HAS write:Author, but auth_002 belongs to org-b, not org-a --
    # the row-level check must still block this. Proves the two checks
    # are genuinely independent, not just one masking the other.
    with pytest.raises(PermissionError):
        wm.propose_write("alice", "Author", "auth_002", "update", {"name": "Hacked"})


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

    real_value = wm.mediator.get_field("org-a", "Author", "auth_001", "name")
    assert real_value == "Ada Lovelace"  # unchanged from conftest.py's seed data


def test_approved_write_actually_updates_the_database(wm):
    pending = wm.propose_write("alice", "Author", "auth_001", "update", {"name": "Ada, Countess of Lovelace"})
    result = wm.confirm_and_execute(pending, approved=True)
    assert result == {"status": "written", "object_id": "auth_001"}

    real_value = wm.mediator.get_field("org-a", "Author", "auth_001", "name")
    assert real_value == "Ada, Countess of Lovelace"
