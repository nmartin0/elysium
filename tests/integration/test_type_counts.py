"""
GET /me/type-counts -- how many of each type the CALLER can see, for the
ontology canvas's nodes (DEV_UI 14.5).
"""

from tests.conftest import with_roles
from tests.integration.test_api import _csrf_headers, _login


def _as(client, username, role, region="us-west"):
    client.app.state.user_directory.create_user(username, "correct-pw", region, role)
    _login(client, username, "correct-pw")


class TestTheCallersCount:
    def test_two_compartments_count_their_own(self, client):
        """MAC applies: the same type, two numbers."""
        _as(client, "west", "customer_service", "us-west")
        west = client.get("/api/me/type-counts").json()["Customer"]["count"]
        _as(client, "east", "customer_service", "us-east")
        east = client.get("/api/me/type-counts").json()["Customer"]["count"]

        assert west > 0 and east > 0 and west != east

    def test_it_matches_the_set_count_for_the_same_person(self, client):
        _as(client, "west", "customer_service")

        listed = client.get("/api/me/type-counts").json()["Transaction"]["count"]
        counted = client.post("/api/objects/Transaction/count", json={},
                              headers=_csrf_headers(client)).json()["count"]

        assert listed == counted


class TestOnlyWhatTheyMayRead:
    def test_a_type_they_cannot_see_is_absent(self, client):
        _as(client, "west", "customer_service_no_email")

        assert "Transaction" not in client.get("/api/me/type-counts").json()

    def test_a_type_they_may_only_discover_gets_no_count(self, client):
        """Counting its objects would say more than that it exists."""
        with_roles(client.app, account_discoverer={"allowed_actions": [
            "discover:Account", "read:Customer", "read:Customer.region"]})
        _as(client, "dee", "account_discoverer")

        counts = client.get("/api/me/type-counts").json()

        assert "Account" not in counts and "Customer" in counts


class TestOneFailureIsOneType:
    def test_a_type_whose_count_fails_is_left_out(self, client, monkeypatch):
        _as(client, "west", "customer_service")
        mediator = client.app.state.generation.mediator
        real = mediator.count_objects

        def failing(user, object_type, *args, **kwargs):
            if object_type == "Transaction":
                raise RuntimeError("not published")
            return real(user, object_type, *args, **kwargs)

        monkeypatch.setattr(mediator, "count_objects", failing)
        counts = client.get("/api/me/type-counts").json()

        assert "Transaction" not in counts and "Customer" in counts
