"""
GET /roles -- every role and its grants, for somebody who may change them.

GATED ON manage:roles, NOT manage:users. Seeing exactly what every role
may do reveals the whole permission model; a manage:users holder sees
role NAMES through /config, never their contents. This endpoint is also
the first thing that CHECKS manage:roles -- without it, the grant would
be accepted and grant nothing.
"""

from tests.integration.test_api import _login  # noqa: F401


def _as(client, username, role):
    client.app.state.user_directory.create_user(
        username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


class TestWhoMaySee:
    def test_manage_users_alone_is_not_enough(self, client):
        """THE SEPARATION FOUNDRY DRAWS: managing membership is not
        managing permissions."""
        _as(client, "ann", "admin")

        assert client.get("/api/roles").status_code == 403

    def test_manage_roles_is(self, client):
        _as(client, "dana", "debug")

        assert client.get("/api/roles").status_code == 200

    def test_an_ordinary_user_is_refused(self, client):
        _as(client, "cy", "customer_service")

        assert client.get("/api/roles").status_code == 403


class TestWhatItSays:
    def test_it_lists_roles_and_their_grants(self, client):
        _as(client, "dana", "debug")

        roles = client.get("/api/roles").json()["roles"]

        assert "manage:roles" in roles["debug"]

    def test_the_source_is_policy_yaml_before_any_edit(self, client):
        """HOW AN ADMINISTRATOR LEARNS that editing policy.yaml has
        stopped working -- it says which is in force."""
        _as(client, "dana", "debug")

        assert client.get("/api/roles").json()["source"] == "policy.yaml"

    def test_it_offers_the_grants_the_editor_needs(self, client):
        _as(client, "dana", "debug")

        grantable = client.get("/api/roles").json()["grantable"]

        assert "read:Customer" in grantable
        assert "manage:roles" in grantable
