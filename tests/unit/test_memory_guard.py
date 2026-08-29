"""
Tests for core/memory/guard.py -- the memory security gate. The whole
point of this class is that it does NOT trust MemoryEntry's stored
captured_security_value; every read goes through a LIVE check_access()
call instead. get() takes a pre-resolved UserRecord now -- resolved
FRESH per request, same as everywhere else in this project.

See test_get_denies_when_access_since_revoked for the case that would
fail if MemoryGuard ever started trusting a stale UserRecord (or the
memory entry's own stored label) instead of the current, live
authorization state.
"""

import pytest

from adapters.inmemory_adapter import InMemoryAdapter
from adapters.sqlite_adapter import SQLiteAdapter
from core.intermediate_layer.auth import resolve_user_record
from core.memory.guard import MemoryGuard
from core.ontology.mediator import DataMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
}

TEST_ROLES = {
    "reader": {"allowed_actions": ["read:Author"]},
}


def _record(user_id):
    # Resolved FRESH on every call -- deliberately, so tests can prove
    # that a NEW resolution after TEST_USERS changes reflects the
    # current state (simulating a new request), while an ALREADY-
    # resolved UserRecord correctly does not retroactively change.
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def guard(test_db_path, test_schema) -> MemoryGuard:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES)
    store = InMemoryAdapter()
    return MemoryGuard(store, mediator, TEST_ROLES)


def test_put_then_get_by_authorized_user(guard):
    guard.put("k1", "Author", "auth_001", "Ada Lovelace", user_id="alice")
    assert guard.get("k1", _record("alice")) == "Ada Lovelace"


def test_get_blocked_for_different_org_mac(guard):
    guard.put("k1", "Author", "auth_001", "Ada Lovelace", user_id="alice")
    # auth_001 is org-a; bob is org-b.
    assert guard.get("k1", _record("bob")) is None


def test_get_missing_key_returns_none(guard):
    assert guard.get("nonexistent_key", _record("alice")) is None


def test_get_denies_when_access_since_revoked(guard):
    # THE test that proves live re-checking, not label-trusting. A
    # FRESH UserRecord is resolved AFTER the mutation below -- simulating
    # a new request arriving after the revocation, which correctly sees
    # the current state (an already-resolved record from BEFORE the
    # revocation would correctly still show the old role -- that's not
    # what this test is proving; a NEW resolution reflecting live state
    # is).
    guard.put("k1", "Author", "auth_001", "Ada Lovelace", user_id="alice")
    assert guard.get("k1", _record("alice")) == "Ada Lovelace"  # works before revocation

    del TEST_USERS["alice"]["role"]  # revoke alice's role
    try:
        assert guard.get("k1", _record("alice")) is None  # a FRESH resolution must now be denied
    finally:
        TEST_USERS["alice"]["role"] = "reader"  # restore for other tests
