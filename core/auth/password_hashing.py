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
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()

DUMMY_HASH = _hasher.hash("dummy-password-never-a-real-account")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        _hasher.verify(stored_hash, password)
        return True
    except VerifyMismatchError:
        return False
