"""
Page sizes and page tokens for /api/v2 (api/v2/paging.py).

A token is a signed position bound to the caller and to the query. The
property every test here protects: a token is useless to anyone else, for
anything else, and later.
"""

import base64
import json

import pytest

from elysium.api.v2 import paging
from elysium.api.v2.paging import InvalidToken, fingerprint, issue, page_size, redeem

KEY = b"k" * 32
QUERY = fingerprint({"type": "base", "objectType": "Customer"}, [], [])


def test_the_default_and_the_maximum_are_named_and_applied():
    assert page_size(None) == paging.DEFAULT_PAGE_SIZE
    assert page_size(paging.MAX_PAGE_SIZE + 1) == paging.MAX_PAGE_SIZE
    assert page_size(10**9) == paging.MAX_PAGE_SIZE
    assert page_size(0) == 1 and page_size(-5) == 1
    assert page_size(7) == 7


def test_a_token_round_trips_to_its_position():
    assert redeem(KEY, issue(KEY, "alice", QUERY, 40), "alice", QUERY) == 40


def test_another_caller_cannot_use_it():
    token = issue(KEY, "alice", QUERY, 40)

    with pytest.raises(InvalidToken):
        redeem(KEY, token, "bob", QUERY)


def test_another_query_cannot_use_it():
    token = issue(KEY, "alice", QUERY, 40)

    with pytest.raises(InvalidToken):
        redeem(KEY, token, "alice", fingerprint({"type": "base", "objectType": "Transaction"}, [], []))
    with pytest.raises(InvalidToken):
        redeem(KEY, token, "alice", fingerprint({"type": "base", "objectType": "Customer"}, [("name", True)], []))


def test_a_token_expires():
    token = issue(KEY, "alice", QUERY, 40, now=1_000_000)

    assert redeem(KEY, token, "alice", QUERY, now=1_000_000 + paging.TOKEN_LIFETIME_SECONDS) == 40
    with pytest.raises(InvalidToken):
        redeem(KEY, token, "alice", QUERY, now=1_000_000 + paging.TOKEN_LIFETIME_SECONDS + 1)


def test_a_token_edited_by_hand_fails():
    payload, _, signature = issue(KEY, "alice", QUERY, 40).partition(".")
    forged = base64.urlsafe_b64encode(json.dumps({"o": 0, "e": 9_999_999_999}).encode()).decode().rstrip("=")

    for bad in (f"{forged}.{signature}", f"{payload}.{signature[:-2]}AA", payload, "", ".", "x.y", "a" * 600):
        with pytest.raises(InvalidToken):
            redeem(KEY, bad, "alice", QUERY)


def test_another_key_cannot_make_or_read_one():
    with pytest.raises(InvalidToken):
        redeem(b"z" * 32, issue(KEY, "alice", QUERY, 40), "alice", QUERY)


def test_a_token_carries_a_position_and_an_expiry_and_nothing_else():
    payload = issue(KEY, "alice", QUERY, 40).partition(".")[0]
    held = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))

    assert set(held) == {"o", "e"}
    assert "alice" not in payload and QUERY not in payload


def test_the_key_is_made_once_and_shared(tmp_path):
    first = paging.signing_key(tmp_path)
    paging._key.cache_clear()  # a second worker process starts with an empty cache

    assert paging.signing_key(tmp_path) == first
    assert len(first) == 32
    assert (tmp_path / "v2_page_token.key").stat().st_mode & 0o077 == 0
    assert list(tmp_path.iterdir()) == [tmp_path / "v2_page_token.key"]


@pytest.mark.parametrize("bad", ["abc.é", "abc.\ud800", "é.abc", "a.béc", "‮.‮"])
def test_a_token_that_is_not_ascii_is_invalid_not_a_fault(bad):
    # hmac.compare_digest raises TypeError on a str that is not ASCII, and
    # the caller chooses the string: that was a 500.
    with pytest.raises(InvalidToken):
        redeem(KEY, bad, "alice", QUERY)
