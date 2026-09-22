"""
Expired sessions are deleted as new ones are made (E-03's second half).

They were never deleted: every session ever issued stayed in the table
for good. (The first half of E-03, storing them hashed, is patch 301.)
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from core.auth.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "credentials.db")


def _rows(store):
    with sqlite3.connect(store._db_path) as conn:
        return {row[0]: row[1] for row in conn.execute("SELECT token, username FROM sessions")}


def test_an_expired_session_goes_when_a_new_one_is_made(store):
    store.create_session("first")  # the table is made on first use
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    with sqlite3.connect(store._db_path) as conn:
        conn.execute("INSERT INTO sessions VALUES ('expired-digest', 'gone', ?, ?)", (past, past))

    store.create_session("alice")

    assert "expired-digest" not in _rows(store)


def test_a_live_session_stays_and_still_works(store):
    live = store.create_session("bob")

    store.create_session("alice")

    assert store.validate_session(live) == "bob"
    assert sorted(_rows(store).values()) == ["alice", "bob"]
