"""
Creating an account cannot hand out an administrative grant you lack.

A REAL HOLE, MEASURED. `admin` holds only manage:users and is refused
/roles. It could create an account in the `debug` role, log in as it,
and reach /roles -- undoing patch 283, which made manage:roles its own
grant precisely so manage:users would not carry it.

KUBERNETES' RULE: "you can only create/update a role binding if you
already have all the permissions contained in the referenced role".
Applied to the administrative plane: manage:* grants must be held to be
handed out. Data grants stay assignable -- the shipped `admin` exists to
create analysts -- and policy.yaml now says what that reaches.
"""

from tests.integration.test_api import _csrf_headers, _login

PASSWORD = "a-password-long-enough-1"


def _as(client, username, role):
    directory = client.app.state.user_directory
    if not directory.user_exists(username):
        directory.create_user(username, PASSWORD, "us-west", role)
    _login(client, username, PASSWORD)


def _create(client, username, role):
    return client.post("/api/users", json={
        "username": username, "password": PASSWORD,
        "mac_value": "us-west", "role_name": role,
    }, headers=_csrf_headers(client))


class TestTheHoleIsClosed:
    def test_admin_cannot_create_an_account_holding_manage_roles(self, client):
        """THE PATH THAT WAS OPEN, end to end."""
        _as(client, "ann", "admin")
        assert client.get("/api/roles").status_code == 403

        response = _create(client, "ann2", "debug")

        assert response.status_code == 403
        assert "manage:roles" in response.json()["detail"]
        assert not client.app.state.user_directory.user_exists("ann2")


class TestWhatStillWorks:
    def test_admin_still_creates_analysts(self, client):
        """THE ADMIN ROLE'S PURPOSE. Data grants stay assignable by
        manage:users -- Kubernetes would demand an explicit bind."""
        _as(client, "ann", "admin")

        assert _create(client, "cy", "customer_service").status_code == 201

    def test_a_holder_of_every_admin_grant_may_create_any_role(self, client):
        _as(client, "dana", "debug")

        assert _create(client, "dana2", "debug").status_code == 201

    def test_an_unknown_role_is_the_directorys_refusal(self, client):
        """NOT A 403: the role does not exist, which is a different
        answer with its own words."""
        _as(client, "ann", "admin")

        assert _create(client, "x", "no_such_role").status_code == 400
