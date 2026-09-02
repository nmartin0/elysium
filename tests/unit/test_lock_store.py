"""Tests for core/lock_store.py."""

from datetime import timedelta
from pathlib import Path

import pytest

from core.lock_store import LockStore


@pytest.fixture
def store(tmp_path: Path) -> LockStore:
    return LockStore(tmp_path / "resource_locks.db")


def test_acquire_then_validate_round_trip(store):
    result = store.acquire("config", "alice")
    assert result is not None
    token, expires_at = result
    assert token
    assert expires_at is not None
    assert store.validate("config", token) is True


def test_acquire_by_different_user_while_held_fails(store):
    store.acquire("config", "alice")
    assert store.acquire("config", "bob") is None


def test_acquire_by_same_user_while_already_held_succeeds_with_a_new_token(store):
    # A real, deliberate case, not an oversight -- see LockStore.
    # acquire()'s own docstring: the same user re-acquiring (a lost
    # tab, a page reload) recovers access, minting a genuinely new
    # token that silently supersedes the old one.
    token1, _ = store.acquire("config", "alice")
    token2, _ = store.acquire("config", "alice")

    assert token2 != token1
    assert store.validate("config", token1) is False
    assert store.validate("config", token2) is True


def test_validate_unknown_resource_returns_false(store):
    assert store.validate("totally-unlocked-resource", "any-token") is False


def test_validate_wrong_token_returns_false(store):
    store.acquire("config", "alice")
    assert store.validate("config", "totally-wrong-token") is False


def test_two_locks_on_different_resources_are_independent(store):
    token_a, _ = store.acquire("config", "alice")
    token_b, _ = store.acquire("other-resource", "bob")

    assert store.validate("config", token_a) is True
    assert store.validate("other-resource", token_b) is True


def test_refresh_with_valid_token_extends_the_lease(store):
    token, _ = store.acquire("config", "alice")
    new_expires_at = store.refresh("config", "alice", token)
    assert new_expires_at is not None
    assert store.validate("config", token) is True


def test_refresh_does_not_change_the_token_itself(store):
    token, _ = store.acquire("config", "alice")
    store.refresh("config", "alice", token)
    # The SAME token still validates -- refresh() extends the existing
    # lease in place, unlike acquire()'s own re-acquire path, which
    # deliberately mints a new one.
    assert store.validate("config", token) is True


def test_refresh_with_stale_superseded_token_fails(store):
    old_token, _ = store.acquire("config", "alice")
    store.acquire("config", "alice")  # re-acquire, supersedes old_token
    assert store.refresh("config", "alice", old_token) is None


def test_refresh_by_wrong_user_fails(store):
    token, _ = store.acquire("config", "alice")
    assert store.refresh("config", "bob", token) is None


def test_refresh_unknown_resource_fails(store):
    assert store.refresh("totally-unlocked-resource", "alice", "any-token") is None


def test_refresh_on_expired_lock_fails_not_resurrects_it(store):
    expired_store = LockStore(store._db_path, lease_duration=timedelta(seconds=-1))
    token, _ = expired_store.acquire("config", "alice")

    assert store.refresh("config", "alice", token) is None


def test_release_by_correct_holder_succeeds(store):
    token, _ = store.acquire("config", "alice")
    assert store.release("config", "alice", token) is True
    assert store.validate("config", token) is False


def test_release_by_wrong_user_fails(store):
    token, _ = store.acquire("config", "alice")
    assert store.release("config", "bob", token) is False
    # The lock is genuinely untouched -- alice's own token still works.
    assert store.validate("config", token) is True


def test_release_with_wrong_token_fails(store):
    token, _ = store.acquire("config", "alice")
    assert store.release("config", "alice", "totally-wrong-token") is False
    assert store.validate("config", token) is True


def test_release_unknown_resource_returns_false(store):
    assert store.release("totally-unlocked-resource", "alice", "any-token") is False


def test_force_release_removes_lock_regardless_of_owner_or_token(store):
    token, _ = store.acquire("config", "alice")
    assert store.force_release("config") is True
    assert store.validate("config", token) is False


def test_force_release_unknown_resource_returns_false(store):
    assert store.force_release("totally-unlocked-resource") is False


def test_after_force_release_a_different_user_can_acquire(store):
    store.acquire("config", "alice")
    store.force_release("config")
    assert store.acquire("config", "bob") is not None


def test_get_status_when_locked(store):
    store.acquire("config", "alice")
    status = store.get_status("config")
    assert status is not None
    assert status["resource_name"] == "config"
    assert status["held_by"] == "alice"
    assert "acquired_at" in status
    assert "expires_at" in status


def test_get_status_when_unlocked_returns_none(store):
    assert store.get_status("totally-unlocked-resource") is None


def test_get_status_after_release_returns_none(store):
    token, _ = store.acquire("config", "alice")
    store.release("config", "alice", token)
    assert store.get_status("config") is None


def test_expired_lock_is_treated_as_unlocked_by_validate(store):
    expired_store = LockStore(store._db_path, lease_duration=timedelta(seconds=-1))
    token, _ = expired_store.acquire("config", "alice")

    assert store.validate("config", token) is False


def test_expired_lock_is_treated_as_unlocked_by_get_status(store):
    expired_store = LockStore(store._db_path, lease_duration=timedelta(seconds=-1))
    expired_store.acquire("config", "alice")

    assert store.get_status("config") is None


def test_after_expiry_a_different_user_can_acquire(store):
    expired_store = LockStore(store._db_path, lease_duration=timedelta(seconds=-1))
    expired_store.acquire("config", "alice")

    # store itself has the REAL (positive) lease_duration -- this call
    # goes through the normal, non-expired acquire() path.
    assert store.acquire("config", "bob") is not None
