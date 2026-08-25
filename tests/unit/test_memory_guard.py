"""
Tests for core/memory/guard.py -- the memory security gate. The whole
point of this class is that it does NOT trust MemoryEntry's stored
captured_security_value; every read goes through a LIVE check_access()
call instead. These tests prove that specifically, not just "memory
works" -- see test_get_denies_when_access_since_revoked for the case
that would fail if MemoryGuard ever started trusting the stored label
instead of re-checking live.
"""

import pytest

from adapters.inmemory_adapter import InMemoryAdapter
from adapters.sqlite_adapter import SQLiteAdapter
from core.memory.guard import MemoryGuard
from core.ontology.mediator import DataMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
}

TEST_ROLES = {
    "reader": {"allowed_actions": ["read:Author"]},
}


@pytest.fixture
def guard(test_db_path, test_schema) -> MemoryGuard:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["silo"] for object_type, type_def in test_schema.items()}
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_USERS, TEST_ROLES, "org_id")
    store = InMemoryAdapter()
    return MemoryGuard(store, mediator, TEST_USERS, TEST_ROLES, "org_id")


def test_put_then_get_by_authorized_user(guard):
    guard.put("k1", "Author", "auth_001", "Ada Lovelace", user_id="alice")
    assert guard.get("k1", user_id="alice") == "Ada Lovelace"


def test_get_blocked_for_different_org_mac(guard):
    guard.put("k1", "Author", "auth_001", "Ada Lovelace", user_id="alice")
    # auth_001 is org-a; bob is org-b.
    assert guard.get("k1", user_id="bob") is None


def test_get_missing_key_returns_none(guard):
    assert guard.get("nonexistent_key", user_id="alice") is None


def test_get_denies_when_access_since_revoked(guard):
    # THE test that proves live re-checking, not label-trusting.
    # Mutate the user registry AFTER the entry was cached -- if
    # MemoryGuard trusted the stored captured_security_value instead of
    # re-deriving live access, this would incorrectly still return the
    # value even though the user's role was just removed.
    guard.put("k1", "Author", "auth_001", "Ada Lovelace", user_id="alice")
    assert guard.get("k1", user_id="alice") == "Ada Lovelace"  # works before revocation

    del TEST_USERS["alice"]["role"]  # revoke alice's role
    try:
        assert guard.get("k1", user_id="alice") is None  # must now be denied
    finally:
        TEST_USERS["alice"]["role"] = "reader"  # restore for other tests
