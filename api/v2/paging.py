"""
paging.py  (page sizes and page tokens)

`pageSize` is a request, clamped to the maximum rather than refused:
precedent says requests for more than the maximum are reduced to it.
`pageToken` is opaque. What it holds is a position (a number) and an
expiry, signed together with WHO it was issued to and WHAT it was issued
for:

    token = b64(position, expiry) . b64(HMAC(key, user id | query | position, expiry))

so a token reused by another user, or on a different set, ordering or
selection, or after it expired, or edited by hand, fails the same way: one
InvalidPageToken, whose words say none of which. It carries no data from
any row, hidden or not -- a position in the caller's OWN result is
something they can already count.

THE KEY lives in the data directory, created once with exclusive
rights, so every worker process and every restart agrees on it. (A key
per process would make a token fail whenever a request landed on
another worker.) Anyone who can read the data directory can already read
far more than a position.

THE POSITION IS AN OFFSET into the result as evaluated for each request.
Like the existing search, that is precedent's "latest results" paging: a
row added or removed between pages can shift later pages. A snapshot
mode is not part of this slice.
"""

import base64
import functools
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500
#: How long a token may be held between two pages.
TOKEN_LIFETIME_SECONDS = 15 * 60

_KEY_FILE = "v2_page_token.key"


class InvalidToken(Exception):
    """Any reason a token cannot be used. Deliberately one reason."""


def page_size(requested: int | None) -> int:
    """The size to serve: the default when none was asked for, never
    below one, never above the maximum."""
    if requested is None:
        return DEFAULT_PAGE_SIZE
    return max(1, min(requested, MAX_PAGE_SIZE))


@functools.lru_cache(maxsize=8)
def _key(directory: str) -> bytes:
    path = Path(directory) / _KEY_FILE
    try:
        return path.read_bytes()
    except FileNotFoundError:
        pass
    candidate = secrets.token_bytes(32)
    temporary = path.with_name(f"{_KEY_FILE}.{secrets.token_hex(8)}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(candidate)
        try:
            # Hard-linked into place: the first process to get here wins
            # and every other reads the winner's, with no moment at which
            # the file exists half-written.
            os.link(temporary, path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return path.read_bytes()


def signing_key(data_dir: Path) -> bytes:
    return _key(str(data_dir))


def fingerprint(*parts: Any) -> str:
    """What a token is bound to: a digest of the query it pages through."""
    canonical = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signature(key: bytes, user_id: str, query: str, payload: str) -> str:
    message = "\0".join([user_id, query, payload]).encode()
    return _b64(hmac.new(key, message, hashlib.sha256).digest())


def issue(key: bytes, user_id: str, query: str, offset: int, now: float | None = None) -> str:
    moment = time.time() if now is None else now
    payload = _b64(json.dumps({"o": offset, "e": int(moment) + TOKEN_LIFETIME_SECONDS},
                              separators=(",", ":")).encode())
    return f"{payload}.{_signature(key, user_id, query, payload)}"


def redeem(key: bytes, token: str, user_id: str, query: str, now: float | None = None) -> int:
    """The position a token holds, or InvalidToken."""
    payload, _, signature = token.partition(".")
    if not payload or not signature or len(token) > 512:
        raise InvalidToken
    # BYTES, not text: compare_digest raises TypeError on a str that is not
    # ASCII, which a caller controls, and that was a 500. A lone surrogate
    # (which can arrive through a query string) cannot be encoded at all.
    try:
        presented = signature.encode()
        expected = _signature(key, user_id, query, payload).encode()
    except UnicodeError:
        raise InvalidToken from None
    if not hmac.compare_digest(presented, expected):
        raise InvalidToken
    try:
        held = json.loads(_unb64(payload))
        offset, expires = int(held["o"]), int(held["e"])
    except (ValueError, KeyError, TypeError):
        raise InvalidToken from None
    if offset < 0 or (time.time() if now is None else now) > expires:
        raise InvalidToken
    return offset
