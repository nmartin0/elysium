"""
Passwords: a policy, changing your own, and an administrator's reset.

NIST SP 800-63B-4 FOR THE POLICY: at least 15 characters (a password is
Elysium's only factor), no composition rules, a blocklist of common and
expected values. Applied where a PERSON chooses a password.

CHANGING YOUR OWN needs the current one, and a wrong guess counts toward
lockout. RESETTING SOMEBODY ELSE'S is impersonation, and is refused on
an account whose administrative grants the resetter lacks -- the rule
patch 298 applied to putting somebody in a role.

AND EVERY ACCOUNT ACTION IS AUDITED -- none were, before this.
"""

import json

from tests.integration.test_api import _csrf_headers, _login

GOOD = "a-long-and-unremarkable-passphrase"
NEWER = "another-perfectly-fine-passphrase"


def _user(client, username, role, password=GOOD):
    directory = client.app.state.user_directory
    if not directory.user_exists(username):
        directory.create_user(username, password, "us-west", role)


def _as(client, username, role, password=GOOD):
    _user(client, username, role, password)
    _login(client, username, password)


def _can_log_in(client, username, password):
    from fastapi.testclient import TestClient

    other = TestClient(client.app)
    # SUCCESS, not 200: login answers 204. A first version of this
    # helper assumed 200, so every login looked like a failure -- the
    # routes were fine and the helper was wrong.
    return other.post("/api/login", json={"username": username, "password": password}).is_success


def _audit(client, action):
    path = client.app.state.runtime_paths.log_dir / "audit.log"
    lines = path.read_text().splitlines() if path.exists() else []
    return [e for e in map(json.loads, lines)
            if e.get("event") == "account" and e.get("action") == action]


class TestThePolicyAtCreation:
    def _create(self, client, username, password):
        return client.post("/api/users", json={
            "username": username, "password": password,
            "mac_value": "us-west", "role_name": "customer_service",
        }, headers=_csrf_headers(client))

    def test_a_short_password_is_refused(self, client):
        _as(client, "ann", "admin")

        response = self._create(client, "cy", "short-pass")

        assert response.status_code == 400
        assert "15" in response.json()["detail"]

    def test_a_password_holding_the_username_is_refused(self, client):
        _as(client, "ann", "admin")

        assert self._create(client, "cyrus", "cyrus-and-a-long-tail").status_code == 400

    def test_a_long_plain_passphrase_is_accepted(self, client):
        """NO COMPOSITION RULES: lower case and spaces are fine."""
        _as(client, "ann", "admin")

        assert self._create(client, "cy", "the long walk home tonight").status_code == 201

    def test_creation_is_audited(self, client):
        _as(client, "ann", "admin")
        self._create(client, "cy", GOOD)

        (entry,) = _audit(client, "create")
        assert entry["actor"] == "ann" and entry["target"] == "cy"
        assert GOOD not in json.dumps(entry)


class TestChangingYourOwn:
    def _change(self, client, current, new):
        return client.post("/api/me/password", json={
            "current_password": current, "new_password": new,
        }, headers=_csrf_headers(client))

    def test_it_changes_it(self, client):
        _as(client, "cy", "customer_service")

        assert self._change(client, GOOD, NEWER).status_code == 200
        assert _can_log_in(client, "cy", NEWER)
        assert not _can_log_in(client, "cy", GOOD)

    def test_it_needs_the_current_password(self, client):
        """A SESSION IS NOT THE PERSON: an unlocked laptop must not be
        enough to take the account for good."""
        _as(client, "cy", "customer_service")

        assert self._change(client, "not-the-current-one", NEWER).status_code == 400
        assert _can_log_in(client, "cy", GOOD)

    def test_wrong_guesses_lock_it_out(self, client):
        """OTHERWISE AN UNTHROTTLED PASSWORD TEST for anybody holding a
        session."""
        _as(client, "cy", "customer_service")
        for _ in range(5):
            self._change(client, "a-wrong-guess-each-time", NEWER)

        assert self._change(client, GOOD, NEWER).status_code == 429

    def test_the_new_one_must_pass_the_policy(self, client):
        _as(client, "cy", "customer_service")

        assert self._change(client, GOOD, "too-short").status_code == 400

    def test_every_other_session_ends_and_this_one_stays(self, client):
        from fastapi.testclient import TestClient

        _user(client, "cy", "customer_service")
        other_device = TestClient(client.app)
        _login(other_device, "cy", GOOD)
        _login(client, "cy", GOOD)

        response = self._change(client, GOOD, NEWER)

        assert response.json()["other_sessions_ended"] == 1
        assert client.get("/api/me").status_code == 200
        assert other_device.get("/api/me").status_code == 401

    def test_it_is_audited_without_the_password(self, client):
        _as(client, "cy", "customer_service")
        self._change(client, GOOD, NEWER)

        entries = _audit(client, "change_password")
        assert entries and NEWER not in json.dumps(entries)


class TestAnAdministratorsReset:
    def _reset(self, client, username, new=NEWER):
        return client.post(f"/api/users/{username}/password",
                           json={"new_password": new}, headers=_csrf_headers(client))

    def test_it_resets_an_analyst(self, client):
        _user(client, "cy", "customer_service")
        _as(client, "ann", "admin")

        assert self._reset(client, "cy").status_code == 200
        assert _can_log_in(client, "cy", NEWER)

    def test_it_ends_every_session_of_the_target(self, client):
        from fastapi.testclient import TestClient

        _user(client, "cy", "customer_service")
        victim = TestClient(client.app)
        _login(victim, "cy", GOOD)
        _as(client, "ann", "admin")

        self._reset(client, "cy")

        assert victim.get("/api/me").status_code == 401

    def test_not_an_account_with_administrative_grants_you_lack(self, client):
        """IMPERSONATION. Whoever sets a password can log in as its
        owner; resetting a debug account would reach manage:roles."""
        _user(client, "dana", "debug")
        _as(client, "ann", "admin")

        response = self._reset(client, "dana")

        assert response.status_code == 403
        assert _can_log_in(client, "dana", GOOD)

    def test_not_yourself(self, client):
        """YOUR OWN asks for the current password; this would skip it."""
        _as(client, "ann", "admin")

        assert self._reset(client, "ann").status_code == 400

    def test_not_without_manage_users(self, client):
        _user(client, "cy", "customer_service")
        _as(client, "cyd", "customer_service")

        assert self._reset(client, "cy").status_code == 403

    def test_the_new_one_must_pass_the_policy(self, client):
        _user(client, "cy", "customer_service")
        _as(client, "ann", "admin")

        assert self._reset(client, "cy", new="short").status_code == 400

    def test_it_is_audited(self, client):
        _user(client, "cy", "customer_service")
        _as(client, "ann", "admin")
        self._reset(client, "cy")

        (entry,) = _audit(client, "reset_password")
        assert entry["actor"] == "ann" and entry["target"] == "cy"
