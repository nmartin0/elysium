"""
Tests for core/auth/credential_store.py. Uses pytest's tmp_path (a real
isolated temp directory per test) for the SQLite file -- no shared state
between tests, no risk of one test's data leaking into another's.
"""

import pytest
from pathlib import Path
from unittest.mock import patch

from core.auth import credential_store
from core.auth.password_hashing import DUMMY_HASH


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "credentials.db"


def test_create_then_verify_round_trip(db_path):
    credential_store.create_credential(db_path, "alice", "hunter2")
    assert credential_store.verify_credential(db_path, "alice", "hunter2") is True


def test_verify_wrong_password_returns_false(db_path):
    credential_store.create_credential(db_path, "alice", "hunter2")
    assert credential_store.verify_credential(db_path, "alice", "wrong") is False


def test_verify_nonexistent_username_returns_false_not_crash(db_path):
    assert credential_store.verify_credential(db_path, "nobody", "anything") is False


def test_create_duplicate_username_raises(db_path):
    credential_store.create_credential(db_path, "alice", "hunter2")
    with pytest.raises(ValueError):
        credential_store.create_credential(db_path, "alice", "different-password")


def test_update_nonexistent_username_raises(db_path):
    with pytest.raises(ValueError):
        credential_store.update_credential(db_path, "nobody", "newpass")


def test_update_actually_changes_the_password(db_path):
    credential_store.create_credential(db_path, "alice", "old-password")
    credential_store.update_credential(db_path, "alice", "new-password")
    assert credential_store.verify_credential(db_path, "alice", "new-password") is True
    assert credential_store.verify_credential(db_path, "alice", "old-password") is False


def test_nonexistent_username_still_performs_real_verification(db_path):
    # THE timing-safety proof: verify_password must be genuinely CALLED
    # (against DUMMY_HASH) even when the username doesn't exist --
    # skipping it would create a real timing side channel revealing
    # which usernames are real.
    credential_store.create_credential(db_path, "alice", "hunter2")

    with patch("core.auth.credential_store.verify_password") as mock_verify:
        mock_verify.return_value = False
        credential_store.verify_credential(db_path, "totally_fake_user", "anything")
        assert mock_verify.called
        assert mock_verify.call_args[0][0] == DUMMY_HASH
