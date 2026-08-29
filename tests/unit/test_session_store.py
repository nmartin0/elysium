"""Tests for core/auth/session_store.py."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from core.auth import session_store


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "credentials.db"


def test_create_then_validate_round_trip(db_path):
    token = session_store.create_session(db_path, "alice")
    assert session_store.validate_session(db_path, token) == "alice"


def test_validate_fake_token_returns_none(db_path):
    assert session_store.validate_session(db_path, "totally-fake-token") is None


def test_two_sessions_for_same_user_have_different_tokens(db_path):
    token1 = session_store.create_session(db_path, "alice")
    token2 = session_store.create_session(db_path, "alice")
    assert token1 != token2


def test_invalidate_actually_removes_the_session(db_path):
    token = session_store.create_session(db_path, "alice")
    session_store.invalidate_session(db_path, token)
    assert session_store.validate_session(db_path, token) is None


def test_expired_session_returns_none(db_path):
    # Force an already-expired session by patching SESSION_LIFETIME to
    # negative for just the creation call.
    with patch.object(session_store, "SESSION_LIFETIME", timedelta(seconds=-1)):
        expired_token = session_store.create_session(db_path, "alice")

    assert session_store.validate_session(db_path, expired_token) is None


def test_invalidate_all_sessions_revokes_every_session_for_that_user(db_path):
    token1 = session_store.create_session(db_path, "alice")
    token2 = session_store.create_session(db_path, "alice")

    session_store.invalidate_all_sessions(db_path, "alice")

    assert session_store.validate_session(db_path, token1) is None
    assert session_store.validate_session(db_path, token2) is None


def test_invalidate_all_sessions_does_not_affect_other_users(db_path):
    alice_token = session_store.create_session(db_path, "alice")
    bob_token = session_store.create_session(db_path, "bob")

    session_store.invalidate_all_sessions(db_path, "alice")

    assert session_store.validate_session(db_path, alice_token) is None
    assert session_store.validate_session(db_path, bob_token) == "bob"
