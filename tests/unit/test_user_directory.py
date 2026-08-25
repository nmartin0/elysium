"""
Tests for core/user_directory.py -- the runtime, database-backed
half of user management (roles stay static in policy.yaml; WHICH
person has WHICH role is what this manages at runtime).

The atomicity tests are the highest-stakes coverage here: create_user()
writes to two tables in one transaction specifically so a crash can
never leave an orphaned credential (can log in, no permissions) or an
orphaned directory entry (has permissions, can't log in).
disable_user() and delete_user() carry the same atomicity discipline
in reverse -- flipping the flag / removing the account AND clearing
every session, in one transaction, so a disabled or deleted account
can never be left holding a still-valid token.
"""

import pytest
from pathlib import Path

from core.auth.credential_store import verify_credential
from core.auth.session_store import create_session, validate_session
from core.user_directory import (
    create_user, get_user_record, is_user_disabled, disable_user, enable_user,
    delete_user, user_exists, list_users,
)

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


def test_user_exists_distinguishes_unknown_from_present(db_path):
    assert user_exists(db_path, "alice") is False
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    assert user_exists(db_path, "alice") is True


def test_freshly_created_user_is_not_disabled(db_path):
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    assert is_user_disabled(db_path, "alice") is False


def test_is_user_disabled_false_for_unknown_user(db_path):
    # "doesn't exist" and "disabled" are different facts -- see
    # user_exists() for the former.
    assert is_user_disabled(db_path, "totally_fake_user") is False


def test_disable_user_flips_the_flag(db_path):
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    disable_user(db_path, "alice")
    assert is_user_disabled(db_path, "alice") is True


def test_disable_user_kills_existing_sessions_atomically(db_path):
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    token = create_session(db_path, "alice")
    assert validate_session(db_path, token) == "alice"

    disable_user(db_path, "alice")

    assert validate_session(db_path, token) is None


def test_disable_user_does_not_touch_the_credential_itself(db_path):
    # The credential still verifies correctly -- is_user_disabled() is
    # a SEPARATE check the caller (api/auth_dependency.py, api/routes.py's
    # /login) is responsible for making, not something baked into
    # verify_credential() itself.
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    disable_user(db_path, "alice")
    assert verify_credential(db_path, "alice", "pw") is True


def test_disable_nonexistent_user_raises(db_path):
    with pytest.raises(ValueError):
        disable_user(db_path, "totally_fake_user")


def test_enable_reverses_disable(db_path):
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    disable_user(db_path, "alice")
    enable_user(db_path, "alice")
    assert is_user_disabled(db_path, "alice") is False


def test_enable_nonexistent_user_raises(db_path):
    with pytest.raises(ValueError):
        enable_user(db_path, "totally_fake_user")


def test_delete_user_removes_credential_directory_and_sessions_atomically(db_path):
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    token = create_session(db_path, "alice")

    delete_user(db_path, "alice")

    assert get_user_record(db_path, "alice").role_name is None
    assert verify_credential(db_path, "alice", "pw") is False
    assert validate_session(db_path, token) is None
    assert user_exists(db_path, "alice") is False


def test_delete_nonexistent_user_raises(db_path):
    with pytest.raises(ValueError):
        delete_user(db_path, "totally_fake_user")


def test_delete_does_not_affect_other_users(db_path):
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    create_user(db_path, TEST_ROLES, "bob", "pw2", "us-east", "analyst")

    delete_user(db_path, "alice")

    assert user_exists(db_path, "alice") is False
    assert user_exists(db_path, "bob") is True
    assert verify_credential(db_path, "bob", "pw2") is True


def test_list_users_empty_when_none_exist(db_path):
    assert list_users(db_path) == []


def test_list_users_returns_correct_metadata_sorted_by_username(db_path):
    create_user(db_path, TEST_ROLES, "bob", "pw2", "us-east", "analyst")
    create_user(db_path, TEST_ROLES, "alice", "pw", "us-west", "analyst")
    disable_user(db_path, "bob")

    users = list_users(db_path)

    assert [u["username"] for u in users] == ["alice", "bob"]  # sorted
    assert users[0] == {"username": "alice", "mac_value": "us-west", "role_name": "analyst", "disabled": False}
    assert users[1] == {"username": "bob", "mac_value": "us-east", "role_name": "analyst", "disabled": True}


def test_list_users_never_includes_password_data(db_path):
    create_user(db_path, TEST_ROLES, "alice", "a-real-secret-password", "us-west", "analyst")

    users = list_users(db_path)

    assert "password" not in users[0]
    assert "password_hash" not in users[0]
    assert "a-real-secret-password" not in str(users)
