"""
Tests for core/auth/credential_store.py. Uses pytest's tmp_path (a real
isolated temp directory per test) for the SQLite file -- no shared state
between tests, no risk of one test's data leaking into another's.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from core.auth.credential_store import CredentialReader, CredentialWriter
from core.auth.database import connection
from core.auth.password_hashing import DUMMY_HASH


@pytest.fixture
def reader(tmp_path: Path) -> CredentialReader:
    # Schema explicitly ensured here, before the Reader is ever
    # constructed -- a real, necessary step, not defensive boilerplate:
    # a genuinely read-only connection can never create the
    # credentials table itself (see core/auth/credential_store.py's own
    # module docstring), so a test exercising the Reader alone, with no
    # prior write, would otherwise fail on "no such table" -- the exact
    # real ordering requirement api/app.py's own explicit startup step
    # exists to guarantee in production.
    db_path = tmp_path / "credentials.db"
    with connection(db_path):
        pass
    return CredentialReader(db_path)


@pytest.fixture
def writer(tmp_path: Path) -> CredentialWriter:
    return CredentialWriter(tmp_path / "credentials.db")


def test_create_then_verify_round_trip(reader, writer):
    writer.create_credential("alice", "hunter2")
    assert reader.verify_credential("alice", "hunter2") is True


def test_verify_wrong_password_returns_false(reader, writer):
    writer.create_credential("alice", "hunter2")
    assert reader.verify_credential("alice", "wrong") is False


def test_verify_nonexistent_username_returns_false_not_crash(reader):
    assert reader.verify_credential("nobody", "anything") is False


def test_create_duplicate_username_raises(writer):
    writer.create_credential("alice", "hunter2")
    with pytest.raises(ValueError):
        writer.create_credential("alice", "different-password")


def test_update_nonexistent_username_raises(writer):
    with pytest.raises(ValueError):
        writer.update_credential("nobody", "newpass")


def test_update_actually_changes_the_password(reader, writer):
    writer.create_credential("alice", "old-password")
    writer.update_credential("alice", "new-password")
    assert reader.verify_credential("alice", "new-password") is True
    assert reader.verify_credential("alice", "old-password") is False


def test_nonexistent_username_still_performs_real_verification(reader, writer):
    # THE timing-safety proof: verify_password must be genuinely CALLED
    # (against DUMMY_HASH) even when the username doesn't exist --
    # skipping it would create a real timing side channel revealing
    # which usernames are real.
    writer.create_credential("alice", "hunter2")

    with patch("core.auth.credential_store.verify_password") as mock_verify:
        mock_verify.return_value = False
        reader.verify_credential("totally_fake_user", "anything")
        assert mock_verify.called
        assert mock_verify.call_args[0][0] == DUMMY_HASH


def test_reader_connection_is_structurally_read_only(reader, writer):
    # A real, direct proof of the actual, new safety property this
    # split exists for -- not just "the tests still pass with two
    # objects instead of one." Confirmed directly, empirically: a real
    # attempt to write through the Reader's own connection is denied
    # at the SQLite engine level itself, not merely unused by this
    # class's own methods.
    writer.create_credential("alice", "hunter2")  # ensures the table exists first
    with reader._connection() as conn, pytest.raises(Exception, match="not authorized"):
        conn.execute("UPDATE credentials SET password_hash = 'x' WHERE username = 'alice'")
