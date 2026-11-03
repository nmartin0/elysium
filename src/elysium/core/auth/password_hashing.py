"""
password_hashing.py  (pure -- zero I/O, zero state, fully testable alone)

Argon2id via argon2-cffi -- the current OWASP-recommended password
hashing algorithm. PasswordHasher()'s defaults are already tuned to
OWASP's recommended parameters; not hand-tuning them is deliberate,
not an oversight -- rolling our own parameter choices here is exactly
the kind of thing to NOT do by hand when a maintained library already
gets it right.

DUMMY_HASH exists for ONE reason: core/auth/credential_store.py's
verify_credential() must take the SAME amount of time whether the
username is real (wrong password) or doesn't exist at all -- otherwise
response timing itself becomes a side channel revealing which
usernames exist (a real, well-known attack against login endpoints).
Computed once at import time -- a genuine hash, verified against for
real, just never a real account's password.
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

DUMMY_HASH = _hasher.hash("dummy-password-never-a-real-account")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """False for a wrong password AND for a hash we cannot verify.

    IT USED TO CATCH ONLY VerifyMismatchError, so a stored hash that
    argon2 could not parse escaped as an exception. Measured against a
    real hasher:

        wrong password     -> False
        empty string       -> RAISES InvalidHashError
        garbage            -> RAISES InvalidHashError
        truncated argon2   -> RAISES VerificationError
        a bcrypt-style row -> RAISES InvalidHashError

    WHY THAT MATTERS MORE THAN IT LOOKS. An exception here reaches the
    login route as a 500 while every other failed login is a uniform
    401. That is a louder username oracle than the timing channel
    DUMMY_HASH exists to close: an attacker does not need to measure
    anything, just read the status code. Uniform denial is one of this
    project's non-negotiables, so returning False is required rather
    than preferred.

    AND IT IS THE FAIL-CLOSED ANSWER ANYWAY. A hash that cannot be
    parsed has not been verified, and "I could not tell" must never
    resolve to "allowed".

    TWO SEPARATE HIERARCHIES, checked rather than assumed:
    VerifyMismatchError derives from VerificationError -> Argon2Error,
    while InvalidHashError derives from ValueError. Catching one does
    not catch the other, which is how this survived.

    STILL NO LOGGING, deliberately -- this module is documented as
    pure, zero I/O and zero state, and a corrupt credential row is a
    data-integrity problem for whoever owns credentials.db rather than
    something a hash function should be writing about.
    """
    try:
        _hasher.verify(stored_hash, password)
        return True
    except (VerificationError, InvalidHashError):
        return False
