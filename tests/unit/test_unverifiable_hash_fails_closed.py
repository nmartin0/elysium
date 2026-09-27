"""A hash we cannot verify is a failed login, not a crash (SEC-21).

`verify_password` caught only `VerifyMismatchError`, so a stored hash
argon2 could not parse escaped as an exception. Measured against a
real hasher:

    wrong password     -> False
    empty string       -> RAISES InvalidHashError
    garbage            -> RAISES InvalidHashError
    truncated argon2   -> RAISES VerificationError
    a bcrypt-style row -> RAISES InvalidHashError

WHY THAT MATTERS MORE THAN IT LOOKS. An exception here reaches the
login route as a 500 while every other failed login is a uniform 401.
That is a LOUDER username oracle than the timing channel DUMMY_HASH
exists to close -- an attacker does not have to measure anything, just
read the status code. Uniform denial is one of this project's
non-negotiables, so returning False is required rather than preferred.

TWO SEPARATE HIERARCHIES, which is how this survived:
`VerifyMismatchError` derives from `VerificationError` -> `Argon2Error`,
while `InvalidHashError` derives from `ValueError`. Catching the one
the happy path needs does not catch the other, and nothing about the
code looks wrong.

REACHABILITY, stated rather than dressed up: it needs a malformed row
in credentials.db -- corruption, a partial restore, a hand-edited
record, or credentials carried over from a different hashing scheme.
Narrow. The failure mode is worse than the cause, which is why it is
worth closing rather than noting.
"""

import pytest

from core.auth.password_hashing import (
    DUMMY_HASH,
    hash_password,
    verify_password,
)

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def stored() -> str:
    return hash_password(PASSWORD)


class TestAnUnverifiableHashIsSimplyFalse:
    @pytest.mark.parametrize("corrupt", [
        "",
        "not-a-hash",
        "$2b$12$abcdefghijklmnopqrstuv",          # a bcrypt row
        "$argon2id$v=19$m=65536,t=3,p=4$short",   # argon2-shaped, truncated
        "\x00\x01binary",
    ])
    def test_it_does_not_raise(self, corrupt):
        assert verify_password(corrupt, PASSWORD) is False

    def test_a_truncated_real_hash_does_not_raise(self, stored):
        """Different exception hierarchy from the ones above --
        VerificationError rather than InvalidHashError."""
        assert verify_password(stored[:20], PASSWORD) is False

    def test_none_of_them_leak_which_failure_it_was(self, stored):
        """The point. A caller cannot tell a corrupt row from a wrong
        password, so the login route answers the same 401 either way
        and there is no oracle."""
        outcomes = {
            verify_password(stored, "wrong-password"),
            verify_password("not-a-hash", PASSWORD),
            verify_password("", PASSWORD),
        }

        assert outcomes == {False}


class TestWhatMustStillWork:
    """THE OPPOSITE DIRECTION. A function that always returned False
    would satisfy every test above and let nobody log in."""

    def test_the_right_password_verifies(self, stored):
        assert verify_password(stored, PASSWORD) is True

    def test_the_wrong_password_does_not(self, stored):
        assert verify_password(stored, "wrong-password") is False

    def test_two_hashes_of_the_same_password_differ_but_both_verify(self):
        """Salted, so the stored value is never a lookup key."""
        first, second = hash_password(PASSWORD), hash_password(PASSWORD)

        assert first != second
        assert verify_password(first, PASSWORD)
        assert verify_password(second, PASSWORD)

    def test_the_dummy_hash_is_a_real_one(self):
        """It exists so an unknown username costs the same work as a
        known one. A malformed dummy would now fail closed silently
        instead of raising, so it is worth pinning that it parses."""
        assert verify_password(DUMMY_HASH, "anything-at-all") is False
        assert DUMMY_HASH.startswith("$argon2")
