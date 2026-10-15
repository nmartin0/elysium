"""
GET /schema/access -- who can see each type and field, by role (DEV_UI 13.3).

The expectations below are read from the fixture's policy.yaml and
ontology_schema.yaml, not from the route's output: a role named
customer_service_no_email must not read email, and so on.
"""

from core.ontology.who_can_see import _compartment
from tests.integration.test_api import _login


def _as(client, username, role):
    client.app.state.user_directory.create_user(username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _access(client):
    _as(client, "dana", "debug")
    response = client.get("/api/schema/access")
    assert response.status_code == 200, response.text
    return response.json()


def _role(access, object_type, role):
    return next(r for r in access[object_type]["roles"] if r["role"] == role)


class TestWhoMayAsk:
    def test_manage_users_alone_is_not_enough(self, client):
        """As /roles: this is the permission model's content."""
        _as(client, "ann", "admin")

        assert client.get("/api/schema/access").status_code == 403

    def test_an_ordinary_user_is_refused(self, client):
        _as(client, "cy", "customer_service")

        assert client.get("/api/schema/access").status_code == 403


class TestFields:
    def test_a_role_without_a_field_grant_cannot_see_it(self, client):
        role = _role(_access(client), "Customer", "customer_service_no_email")

        assert role["fields"]["email"] is None
        assert role["fields"]["name"] == "read"

    def test_discover_without_read_is_its_own_answer(self, client):
        role = _role(_access(client), "Customer", "customer_service_sees_email_exists")

        assert role["fields"]["email"] == "discover"

    def test_every_field_is_answered_in_declaration_order(self, client):
        role = _role(_access(client), "Customer", "customer_service")

        assert list(role["fields"])[:3] == ["region", "name", "email"]

    def test_a_role_that_cannot_discover_the_type_is_named_apart(self, client):
        access = _access(client)

        assert "admin" in access["Customer"]["no_access"]
        assert "admin" not in [r["role"] for r in access["Customer"]["roles"]]


class TestWhatChangesIt:
    def test_the_actions_on_the_type_each_role_may_run(self, client):
        access = _access(client)

        assert _role(access, "Customer", "editor")["actions"] == [
            "CreateCustomer", "UpdateCustomerName"]
        assert _role(access, "Customer", "customer_service")["actions"] == []

    def test_an_action_on_another_type_is_not_listed(self, client):
        """debug may run TransferFunds, which changes Accounts."""
        assert "TransferFunds" not in _role(_access(client), "Customer", "debug")["actions"]


class TestCompartments:
    def test_a_type_holding_its_own(self, client):
        assert _access(client)["Customer"]["compartment"] == {
            "attribute": "region", "path": [], "type": "Customer", "field": "region"}

    def test_a_borrowed_one_is_followed_to_its_end(self, client):
        assert _access(client)["Transaction"]["compartment"] == {
            "attribute": "region", "path": [{"type": "Transaction", "field": "customer_id"}],
            "type": "Customer", "field": "region"}

    def test_a_loop_or_a_break_answers_nothing_rather_than_hanging(self):
        looped = {"A": {"security": {"via_field": "b"}, "fields": {"b": {"target": "B"}}},
                  "B": {"security": {"via_field": "a"}, "fields": {"a": {"target": "A"}}}}
        broken = {"A": {"security": {"via_field": "b"}, "fields": {}}}

        assert _compartment(looped, "A", "region") is None
        assert _compartment(broken, "A", "region") is None


class TestPeople:
    def test_how_many_hold_each_role(self, client):
        access = _access(client)

        # dana, created above, is the one debug account.
        assert _role(access, "Customer", "debug")["holders"] == 1
        assert _role(access, "Customer", "editor")["holders"] == 0
