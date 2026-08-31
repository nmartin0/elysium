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

from pathlib import Path

import pytest

from core.auth.credential_store import CredentialStore
from core.auth.session_store import SessionStore
from core.user_directory import UserDirectory

TEST_ROLES = {"analyst": {"allowed_actions": ["read:Employee"]}}


@pytest.fixture
def directory_and_stores(tmp_path: Path):
    db_path = tmp_path / "db.sqlite"
    return UserDirectory(db_path, TEST_ROLES), CredentialStore(db_path), SessionStore(db_path)


def test_create_user_rejects_unknown_role_before_any_write(directory_and_stores):
    directory, _, _ = directory_and_stores
    with pytest.raises(ValueError):
        directory.create_user("alice", "pw", "us-west", "nonexistent_role")

    # Nothing should exist for a user whose creation was rejected.
    record = directory.get_user_record("alice")
    assert record.role_name is None


def test_create_then_get_user_record_round_trip(directory_and_stores):
    directory, credentials, _ = directory_and_stores
    directory.create_user("alice", "hunter2", "us-west", "analyst")

    record = directory.get_user_record("alice")
    assert record.user_id == "alice"
    assert record.security_value == "us-west"
    assert record.role_name == "analyst"
    assert credentials.verify_credential("alice", "hunter2") is True


def test_get_user_record_for_nonexistent_user_returns_empty_record_not_crash(directory_and_stores):
    directory, _, _ = directory_and_stores
    record = directory.get_user_record("nobody")
    assert record.user_id == "nobody"
    assert record.security_value is None
    assert record.role_name is None


def test_create_user_allows_none_mac_value(directory_and_stores):
    directory, _, _ = directory_and_stores
    directory.create_user("alice", "hunter2", None, "analyst")
    record = directory.get_user_record("alice")
    assert record.security_value is None
    assert record.role_name == "analyst"


def test_duplicate_username_atomicity_leaves_zero_partial_state(directory_and_stores):
    # THE atomicity proof: a duplicate-username failure must leave
    # BOTH the users table AND the credentials table completely
    # untouched by the failed attempt -- not one written and the other
    # not, and not a partial overwrite of the original.
    directory, credentials, _ = directory_and_stores
    directory.create_user("alice", "original-password", "us-west", "analyst")

    with pytest.raises(ValueError):
        directory.create_user("alice", "different-password", "us-east", "analyst")

    record = directory.get_user_record("alice")
    assert record.security_value == "us-west"  # unchanged, NOT us-east
    assert credentials.verify_credential("alice", "original-password") is True
    assert credentials.verify_credential("alice", "different-password") is False


def test_user_exists_distinguishes_unknown_from_present(directory_and_stores):
    directory, _, _ = directory_and_stores
    assert directory.user_exists("alice") is False
    directory.create_user("alice", "pw", "us-west", "analyst")
    assert directory.user_exists("alice") is True


def test_freshly_created_user_is_not_disabled(directory_and_stores):
    directory, _, _ = directory_and_stores
    directory.create_user("alice", "pw", "us-west", "analyst")
    assert directory.is_user_disabled("alice") is False


def test_is_user_disabled_false_for_unknown_user(directory_and_stores):
    # "doesn't exist" and "disabled" are different facts -- see
    # user_exists() for the former.
    directory, _, _ = directory_and_stores
    assert directory.is_user_disabled("totally_fake_user") is False


def test_disable_user_flips_the_flag(directory_and_stores):
    directory, _, _ = directory_and_stores
    directory.create_user("alice", "pw", "us-west", "analyst")
    directory.disable_user("alice")
    assert directory.is_user_disabled("alice") is True


def test_disable_user_kills_existing_sessions_atomically(directory_and_stores):
    directory, _, sessions = directory_and_stores
    directory.create_user("alice", "pw", "us-west", "analyst")
    token = sessions.create_session("alice")
    assert sessions.validate_session(token) == "alice"

    directory.disable_user("alice")

    assert sessions.validate_session(token) is None


def test_disable_user_does_not_touch_the_credential_itself(directory_and_stores):
    # The credential still verifies correctly -- is_user_disabled() is
    # a SEPARATE check the caller (api/auth_dependency.py, api/routes.py's
    # /login) is responsible for making, not something baked into
    # verify_credential() itself.
    directory, credentials, _ = directory_and_stores
    directory.create_user("alice", "pw", "us-west", "analyst")
    directory.disable_user("alice")
    assert credentials.verify_credential("alice", "pw") is True


def test_disable_nonexistent_user_raises(directory_and_stores):
    directory, _, _ = directory_and_stores
    with pytest.raises(ValueError):
        directory.disable_user("totally_fake_user")


def test_enable_reverses_disable(directory_and_stores):
    directory, _, _ = directory_and_stores
    directory.create_user("alice", "pw", "us-west", "analyst")
    directory.disable_user("alice")
    directory.enable_user("alice")
    assert directory.is_user_disabled("alice") is False


def test_enable_nonexistent_user_raises(directory_and_stores):
    directory, _, _ = directory_and_stores
    with pytest.raises(ValueError):
        directory.enable_user("totally_fake_user")


def test_delete_user_removes_credential_directory_and_sessions_atomically(directory_and_stores):
    directory, credentials, sessions = directory_and_stores
    directory.create_user("alice", "pw", "us-west", "analyst")
    token = sessions.create_session("alice")

    directory.delete_user("alice")

    assert directory.get_user_record("alice").role_name is None
    assert credentials.verify_credential("alice", "pw") is False
    assert sessions.validate_session(token) is None
    assert directory.user_exists("alice") is False


def test_delete_nonexistent_user_raises(directory_and_stores):
    directory, _, _ = directory_and_stores
    with pytest.raises(ValueError):
        directory.delete_user("totally_fake_user")


def test_delete_does_not_affect_other_users(directory_and_stores):
    directory, credentials, _ = directory_and_stores
    directory.create_user("alice", "pw", "us-west", "analyst")
    directory.create_user("bob", "pw2", "us-east", "analyst")

    directory.delete_user("alice")

    assert directory.user_exists("alice") is False
    assert directory.user_exists("bob") is True
    assert credentials.verify_credential("bob", "pw2") is True


def test_list_users_empty_when_none_exist(directory_and_stores):
    directory, _, _ = directory_and_stores
    assert directory.list_users() == []


def test_list_users_returns_correct_metadata_sorted_by_username(directory_and_stores):
    directory, _, _ = directory_and_stores
    directory.create_user("bob", "pw2", "us-east", "analyst")
    directory.create_user("alice", "pw", "us-west", "analyst")
    directory.disable_user("bob")

    users = directory.list_users()

    assert [u["username"] for u in users] == ["alice", "bob"]  # sorted
    assert users[0] == {"username": "alice", "mac_value": "us-west", "role_name": "analyst", "disabled": False}
    assert users[1] == {"username": "bob", "mac_value": "us-east", "role_name": "analyst", "disabled": True}


def test_list_users_never_includes_password_data(directory_and_stores):
    directory, _, _ = directory_and_stores
    directory.create_user("alice", "a-real-secret-password", "us-west", "analyst")

    users = directory.list_users()

    assert "password" not in users[0]
    assert "password_hash" not in users[0]
    assert "a-real-secret-password" not in str(users)
