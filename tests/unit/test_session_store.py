"""Tests for core/auth/session_store.py."""

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from core.auth import session_store
from core.auth.session_store import SessionStore


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "credentials.db")


def test_create_then_validate_round_trip(store):
    token = store.create_session("alice")
    assert store.validate_session(token) == "alice"


def test_validate_fake_token_returns_none(store):
    assert store.validate_session("totally-fake-token") is None


def test_two_sessions_for_same_user_have_different_tokens(store):
    token1 = store.create_session("alice")
    token2 = store.create_session("alice")
    assert token1 != token2


def test_invalidate_actually_removes_the_session(store):
    token = store.create_session("alice")
    store.invalidate_session(token)
    assert store.validate_session(token) is None


def test_expired_session_returns_none(store):
    # Force an already-expired session by patching SESSION_LIFETIME to
    # negative for just the creation call. Still a module-level
    # constant, patched the same way regardless of create_session()
    # now being a method.
    with patch.object(session_store, "SESSION_LIFETIME", timedelta(seconds=-1)):
        expired_token = store.create_session("alice")

    assert store.validate_session(expired_token) is None


def test_invalidate_all_sessions_revokes_every_session_for_that_user(store):
    token1 = store.create_session("alice")
    token2 = store.create_session("alice")

    store.invalidate_all_sessions("alice")

    assert store.validate_session(token1) is None
    assert store.validate_session(token2) is None


def test_invalidate_all_sessions_does_not_affect_other_users(store):
    alice_token = store.create_session("alice")
    bob_token = store.create_session("bob")

    store.invalidate_all_sessions("alice")

    assert store.validate_session(alice_token) is None
    assert store.validate_session(bob_token) == "bob"
