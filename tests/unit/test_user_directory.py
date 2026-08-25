"""
Tests for core/user_directory.py -- the runtime, database-backed
half of user management (roles stay static in policy.yaml; WHICH
person has WHICH role is what this manages at runtime).

The atomicity tests are the highest-stakes coverage here: create_user()
writes to two tables in one transaction specifically so a crash can
never leave an orphaned credential (can log in, no permissions) or an
orphaned directory entry (has permissions, can't log in).
"""

import pytest
from pathlib import Path

from core.auth.credential_store import verify_credential
from core.user_directory import create_user, get_user_record

TEST_ROLES = {"analyst": {"allowed_actions": ["read:Employee"]}}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "db.sqlite"


def test_create_user_rejects_unknown_role_before_any_write(db_path):
    with pytest.raises(ValueError):
        create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "nonexistent_role")

    # Nothing should exist for a user whose creation was rejected.
    record = get_user_record(db_path, "alice")
    assert record.role_name is None


def test_create_then_get_user_record_round_trip(db_path):
    create_user(db_path, TEST_ROLES, "alice", "hunter2", "us-west", "analyst")

    record = get_user_record(db_path, "alice")
    assert record.user_id == "alice"
    assert record.security_value == "us-west"
    assert record.role_name == "analyst"
    assert verify_credential(db_path, "alice", "hunter2") is True


def test_get_user_record_for_nonexistent_user_returns_empty_record_not_crash(db_path):
    record = get_user_record(db_path, "nobody")
    assert record.user_id == "nobody"
    assert record.security_value is None
    assert record.role_name is None


def test_create_user_allows_none_mac_value(db_path):
    create_user(db_path, TEST_ROLES, "alice", "hunter2", None, "analyst")
    record = get_user_record(db_path, "alice")
    assert record.security_value is None
    assert record.role_name == "analyst"


def test_duplicate_username_atomicity_leaves_zero_partial_state(db_path):
    # THE atomicity proof: a duplicate-username failure must leave
    # BOTH the users table AND the credentials table completely
    # untouched by the failed attempt -- not one written and the other
    # not, and not a partial overwrite of the original.
    create_user(db_path, TEST_ROLES, "alice", "original-password", "us-west", "analyst")

    with pytest.raises(ValueError):
        create_user(db_path, TEST_ROLES, "alice", "different-password", "us-east", "analyst")

    record = get_user_record(db_path, "alice")
    assert record.security_value == "us-west"  # unchanged, NOT us-east
    assert verify_credential(db_path, "alice", "original-password") is True
    assert verify_credential(db_path, "alice", "different-password") is False
