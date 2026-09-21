"""
Session tokens are stored as SHA-256 hashes, never raw.

A RAW TOKEN IN credentials.db IS A LIVE SESSION for anybody who can read
the file -- a backup, a copy, a misplaced permission. Lucia's reasoning,
followed: the token is 256 random bits, so a FAST hash is enough; a
slow one protects a guessable secret, and this is not one.
"""

import hashlib
import sqlite3

from core.auth.auth_cookies import SESSION_COOKIE_NAME
from tests.integration.test_api import _login

PASSWORD = "a-long-and-unremarkable-passphrase"


def _stored(client):
    path = client.app.state.credentials_db_path
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT token FROM sessions")]
    finally:
        conn.close()


def _logged_in(client, username="cy"):
    client.app.state.user_directory.create_user(username, PASSWORD, "us-west", "customer_service")
    _login(client, username, PASSWORD)
    return client.cookies.get(SESSION_COOKIE_NAME)


class TestTheDatabaseHoldsNoToken:
    def test_what_is_stored_is_the_hash(self, client):
        token = _logged_in(client)

        stored = _stored(client)

        assert token not in stored
        assert hashlib.sha256(token.encode()).hexdigest() in stored

    def test_a_copied_database_yields_no_usable_session(self, client):
        """THE POINT. What an attacker reads from the file, presented as
        a cookie, is refused."""
        _logged_in(client)
        (stolen,) = _stored(client)

        from fastapi.testclient import TestClient

        attacker = TestClient(client.app)
        attacker.cookies.set(SESSION_COOKIE_NAME, stolen)

        assert attacker.get("/api/me").status_code == 401

    def test_the_real_token_still_works(self, client):
        _logged_in(client)

        assert client.get("/api/me").status_code == 200


class TestTheUpgradeDestroysRawTokens:
    def test_raw_rows_are_deleted_and_hashed_rows_kept(self, tmp_path):
        """THE RAW ROWS ARE THE LEAK, so they are destroyed, not left to
        expire. Told apart by length: 43 raw, 64 hashed."""
        from core.auth.database import SCHEMA

        path = tmp_path / "credentials.db"
        conn = sqlite3.connect(path)
        conn.executescript(SCHEMA)
        raw = "r" * 43
        hashed = "h" * 64
        for token in (raw, hashed):
            conn.execute("INSERT INTO sessions VALUES (?, 'cy', 't', '2999-01-01T00:00:00+00:00')", (token,))
        conn.commit()
        conn.close()

        from core.auth.database import connection

        with connection(path) as live:
            left = {row[0] for row in live.execute("SELECT token FROM sessions")}

        assert left == {hashed}


class TestAnOlderUsersTableGainsTheColumn:
    def test_must_change_password_is_added_on_open(self, tmp_path):
        """A DEPLOYMENT FROM BEFORE THE FLAG has a users table without
        it. Patch 274 was a new column with no migration; this pins that
        the flag is not another."""
        path = tmp_path / "credentials.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE users (username TEXT PRIMARY KEY, mac_value TEXT, "
            "role_name TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0)",
        )
        conn.execute("INSERT INTO users VALUES ('old', 'us-west', 'admin', 0)")
        conn.commit()
        conn.close()

        from core.user_directory import UserDirectory

        directory = UserDirectory(path, {"admin": {"allowed_actions": []}})

        assert directory.must_change_password("old") is False
