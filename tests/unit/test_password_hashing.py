"""Tests for core/auth/password_hashing.py -- pure, no I/O, no fixtures needed."""

from core.auth.password_hashing import hash_password, verify_password, DUMMY_HASH


def test_hash_is_not_the_plaintext():
    assert hash_password("secret123") != "secret123"


def test_same_password_hashed_twice_produces_different_hashes():
    # Proves real per-hash salting -- if this failed, two users with the
    # same password would have identical stored hashes, a real leak.
    assert hash_password("secret123") != hash_password("secret123")


def test_verify_correct_password():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password(h, "correct-horse-battery-staple") is True


def test_verify_wrong_password():
    h = hash_password("correct-horse-battery-staple")
    assert verify_password(h, "wrong-password") is False


def test_dummy_hash_is_a_real_valid_argon2_hash():
    assert DUMMY_HASH.startswith("$argon2id$")
    assert verify_password(DUMMY_HASH, "dummy-password-never-a-real-account") is True
