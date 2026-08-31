"""
Tests for core/auth/credential_store.py. Uses pytest's tmp_path (a real
isolated temp directory per test) for the SQLite file -- no shared state
between tests, no risk of one test's data leaking into another's.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.auth.credential_store import CredentialStore
from core.auth.password_hashing import DUMMY_HASH


@pytest.fixture
def store(tmp_path: Path) -> CredentialStore:
    return CredentialStore(tmp_path / "credentials.db")


def test_create_then_verify_round_trip(store):
    store.create_credential("alice", "hunter2")
    assert store.verify_credential("alice", "hunter2") is True


def test_verify_wrong_password_returns_false(store):
    store.create_credential("alice", "hunter2")
    assert store.verify_credential("alice", "wrong") is False


def test_verify_nonexistent_username_returns_false_not_crash(store):
    assert store.verify_credential("nobody", "anything") is False


def test_create_duplicate_username_raises(store):
    store.create_credential("alice", "hunter2")
    with pytest.raises(ValueError):
        store.create_credential("alice", "different-password")


def test_update_nonexistent_username_raises(store):
    with pytest.raises(ValueError):
        store.update_credential("nobody", "newpass")


def test_update_actually_changes_the_password(store):
    store.create_credential("alice", "old-password")
    store.update_credential("alice", "new-password")
    assert store.verify_credential("alice", "new-password") is True
    assert store.verify_credential("alice", "old-password") is False


def test_nonexistent_username_still_performs_real_verification(store):
    # THE timing-safety proof: verify_password must be genuinely CALLED
    # (against DUMMY_HASH) even when the username doesn't exist --
    # skipping it would create a real timing side channel revealing
    # which usernames are real.
    store.create_credential("alice", "hunter2")

    with patch("core.auth.credential_store.verify_password") as mock_verify:
        mock_verify.return_value = False
        store.verify_credential("totally_fake_user", "anything")
        assert mock_verify.called
        assert mock_verify.call_args[0][0] == DUMMY_HASH
