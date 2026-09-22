"""
Before authentication: validation errors carry no values (E-01), login
fields are bounded, and expired attempt rows are deleted (E-02).

E-01, MEASURED BEFORE: a login with only a password returned 422 WITH
THAT PASSWORD in it, and /me/password echoed the caller's CURRENT one.

E-02, MEASURED BEFORE: a 20,000-character username wrote a
login_attempts row; a 200,000-character password was hashed; expired
rows were never deleted. These assert ROW COUNTS and CALLS, not only
statuses -- a 401 alone cannot show that nothing was written.
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from core.auth.limits import MAX_LOGIN_PASSWORD_LENGTH, MAX_USERNAME_LENGTH
from core.auth.login_attempt_tracker import WINDOW
from tests.integration.test_api import _csrf_headers, _login

PW = "a-long-and-unremarkable-passphrase"
SECRET = "correct-horse-battery-staple-secret"


def _rows(client):
    db = client.app.state.login_attempt_tracker._db_path
    with sqlite3.connect(db) as conn:
        return conn.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0]


def _keys_anywhere(value):
    if isinstance(value, dict):
        yield from value
        for item in value.values():
            yield from _keys_anywhere(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys_anywhere(item)


class TestValidationErrorsCarryNoValues:
    def test_a_login_missing_its_username_does_not_echo_the_password(self, client):
        response = client.post("/api/login", json={"password": SECRET})

        assert response.status_code == 422
        assert SECRET not in response.text

    def test_changing_a_password_does_not_echo_the_current_one(self, client):
        client.app.state.user_directory.create_user("dana", PW, "us-west", "debug")
        _login(client, "dana", PW)

        response = client.post("/api/me/password", json={"current_password": PW},
                               headers=_csrf_headers(client))

        assert response.status_code == 422
        assert PW not in response.text

    def test_no_error_carries_input_or_ctx_but_each_says_where_and_what(self, client):
        response = client.post("/api/login", json={"username": 42, "password": ["x"]})

        detail = response.json()["detail"]
        assert detail and all("loc" in error and "msg" in error for error in detail)
        assert not {"input", "ctx"} & set(_keys_anywhere(detail))


class TestOversizedFieldsAtLogin:
    def test_a_huge_username_gets_the_same_401_and_writes_no_row(self, client):
        before = _rows(client)

        response = client.post("/api/login", json={"username": "u" * 20_000, "password": PW})

        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password"
        assert _rows(client) == before

    def test_a_huge_password_is_never_hashed(self, client, monkeypatch):
        verified = []
        store = client.app.state.credential_store
        real = store.verify_credential
        monkeypatch.setattr(store, "verify_credential", lambda u, p: verified.append(len(p)) or real(u, p))

        response = client.post("/api/login", json={"username": "dana", "password": "p" * 200_000})

        assert response.status_code == 401
        assert verified == []

    @pytest.mark.parametrize("length, writes", [(MAX_USERNAME_LENGTH, 1), (MAX_USERNAME_LENGTH + 1, 0)])
    def test_the_username_limit_is_exact(self, client, length, writes):
        before = _rows(client)

        client.post("/api/login", json={"username": "u" * length, "password": PW})

        assert _rows(client) - before == writes

    @pytest.mark.parametrize(
        "length, hashed", [(MAX_LOGIN_PASSWORD_LENGTH, True), (MAX_LOGIN_PASSWORD_LENGTH + 1, False)],
    )
    def test_the_password_limit_is_exact(self, client, monkeypatch, length, hashed):
        verified = []
        store = client.app.state.credential_store
        real = store.verify_credential
        monkeypatch.setattr(store, "verify_credential", lambda u, p: verified.append(1) or real(u, p))

        client.post("/api/login", json={"username": "dana", "password": "p" * length})

        assert bool(verified) is hashed

    def test_an_account_whose_password_predates_the_policy_still_logs_in(self, client):
        """WHY 1,024, NOT THE POLICY'S 256: the policy applies when a
        password is SET, since patch 300. One set before may be longer."""
        long_password = "an old passphrase " * 20  # 360 characters
        client.app.state.user_directory.create_user("old_timer", long_password, "us-west", "debug")

        response = client.post("/api/login", json={"username": "old_timer", "password": long_password})

        assert response.status_code == 204


class TestAccountCreationAgrees:
    def test_a_username_login_would_refuse_cannot_be_created(self, client):
        with pytest.raises(ValueError, match="at most"):
            client.app.state.user_directory.create_user("u" * (MAX_USERNAME_LENGTH + 1), PW, "us-west", "debug")

    def test_the_longest_login_accepts_can(self, client):
        client.app.state.user_directory.create_user("u" * MAX_USERNAME_LENGTH, PW, "us-west", "debug")


class TestExpiredAttemptsAreDeleted:
    def test_an_expired_row_goes_and_a_live_one_stays(self, client):
        db = client.app.state.login_attempt_tracker._db_path
        old = (datetime.now(UTC) - WINDOW - timedelta(minutes=1)).isoformat()
        live = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        with sqlite3.connect(db) as conn:
            conn.execute("INSERT INTO login_attempts VALUES ('long_gone', 3, ?)", (old,))
            conn.execute("INSERT INTO login_attempts VALUES ('still_counting', 2, ?)", (live,))

        client.post("/api/login", json={"username": "someone_else", "password": "wrong-but-long-enough"})

        with sqlite3.connect(db) as conn:
            names = {row[0] for row in conn.execute("SELECT username FROM login_attempts")}
        assert "long_gone" not in names
        assert {"still_counting", "someone_else"} <= names
