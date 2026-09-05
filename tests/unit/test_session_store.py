"""Tests for core/auth/session_store.py."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from core.auth import session_store
from core.auth.database import connection
from core.auth.session_store import SessionReader, SessionWriter


@pytest.fixture
def reader(tmp_path: Path) -> SessionReader:
    # Schema explicitly ensured here, before the Reader is ever
    # constructed -- a real, necessary step, not defensive boilerplate:
    # a genuinely read-only connection can never create the sessions
    # table itself (see core/auth/session_store.py's own module
    # docstring), so a test exercising the Reader alone, with no prior
    # write, would otherwise fail on "no such table" -- the exact real
    # ordering requirement api/app.py's own explicit startup step
    # exists to guarantee in production.
    db_path = tmp_path / "credentials.db"
    with connection(db_path):
        pass
    return SessionReader(db_path)


@pytest.fixture
def writer(tmp_path: Path) -> SessionWriter:
    return SessionWriter(tmp_path / "credentials.db")


def test_create_then_validate_round_trip(reader, writer):
    token = writer.create_session("alice")
    assert reader.validate_session(token) == "alice"


def test_validate_fake_token_returns_none(reader):
    assert reader.validate_session("totally-fake-token") is None


def test_two_sessions_for_same_user_have_different_tokens(writer):
    token1 = writer.create_session("alice")
    token2 = writer.create_session("alice")
    assert token1 != token2


def test_invalidate_actually_removes_the_session(reader, writer):
    token = writer.create_session("alice")
    writer.invalidate_session(token)
    assert reader.validate_session(token) is None


def test_expired_session_returns_none(reader, writer):
    # Force an already-expired session by patching SESSION_LIFETIME to
    # negative for just the creation call. Still a module-level
    # constant, patched the same way regardless of create_session()
    # now being a method on a genuinely different class than
    # validate_session().
    with patch.object(session_store, "SESSION_LIFETIME", timedelta(seconds=-1)):
        expired_token = writer.create_session("alice")

    assert reader.validate_session(expired_token) is None


def test_invalidate_all_sessions_revokes_every_session_for_that_user(reader, writer):
    token1 = writer.create_session("alice")
    token2 = writer.create_session("alice")

    writer.invalidate_all_sessions("alice")

    assert reader.validate_session(token1) is None
    assert reader.validate_session(token2) is None


def test_invalidate_all_sessions_does_not_affect_other_users(reader, writer):
    alice_token = writer.create_session("alice")
    bob_token = writer.create_session("bob")

    writer.invalidate_all_sessions("alice")

    assert reader.validate_session(alice_token) is None
    assert reader.validate_session(bob_token) == "bob"


def test_reader_connection_is_structurally_read_only(reader, writer):
    # A real, direct proof of the actual, new safety property this
    # split exists for -- not just "the tests still pass with two
    # objects instead of one." Confirmed directly, empirically: a real
    # attempt to write through the Reader's own connection is denied
    # at the SQLite engine level itself, not merely unused by this
    # class's own methods.
    token = writer.create_session("alice")  # ensures the table exists first
    with reader._connection() as conn, pytest.raises(Exception, match="not authorized"):
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
