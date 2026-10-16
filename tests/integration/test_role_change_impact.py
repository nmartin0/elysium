"""
A role change in ACCESS terms (DEV_UI 13.5): POST /roles/changes/preview,
and the same on every pending change.

"Before saving, the diff stated in ACCESS TERMS rather than config
terms." The expectations are read from the fixture's policy.yaml: the
customer_service role reads Customer.email and every Customer field, and
cannot discover Account.
"""

import dataclasses

from core.role_impact import role_change_impact
from tests.integration.test_api import _csrf_headers, _login


def _as(client, username, role="debug"):
    directory = client.app.state.user_directory
    if not directory.user_exists(username):
        directory.create_user(username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _grants(client, role):
    return client.get("/api/roles").json()["roles"][role]


def _preview(client, role, grants):
    return client.post("/api/roles/changes/preview", json={"role_name": role, "grants": grants},
                       headers=_csrf_headers(client))


class TestWhatItSays:
    def test_removing_a_field_grant_is_a_field_it_can_no_longer_read(self, client):
        _as(client, "dana")
        grants = [g for g in _grants(client, "customer_service") if g != "read:Customer.email"]

        impact = _preview(client, "customer_service", grants).json()

        assert impact["fields_lost"] == [
            {"type": "Customer", "field": "email", "from": "read", "to": None}]
        assert impact["fields_gained"] == [] and impact["types_lost"] == []

    def test_a_new_type_is_said_once_not_field_by_field(self, client):
        _as(client, "dana")
        grants = [*_grants(client, "customer_service"), "read:Account", "read:Account.balance"]

        impact = _preview(client, "customer_service", grants).json()

        assert impact["types_gained"] == [{"type": "Account", "from": None, "to": "read"}]
        assert impact["fields_gained"] == []

    def test_actions_and_administration(self, client):
        _as(client, "dana")
        grants = [*_grants(client, "customer_service"), "execute:UpdateCustomerName", "manage:users"]

        impact = _preview(client, "customer_service", grants).json()

        assert impact["actions_gained"] == ["UpdateCustomerName"]
        assert impact["other_gained"] == ["manage:users"]

    def test_how_many_people_it_is(self, client):
        client.app.state.user_directory.create_user("cy", "pw", "us-west", "customer_service")
        client.app.state.user_directory.create_user("cat", "pw", "us-east", "customer_service")
        _as(client, "dana")

        grants = [g for g in _grants(client, "customer_service") if g != "read:Customer.email"]
        impact = _preview(client, "customer_service", grants).json()

        assert impact["holders"] == 2

    def test_removing_a_role_takes_everything_it_could_see(self, client):
        _as(client, "dana")

        impact = _preview(client, "customer_service_no_email", None).json()

        assert impact["removes_role"] is True
        assert {"type": "Customer", "from": "read", "to": None} in impact["types_lost"]


class TestItChangesNothingAndRefusesWhatProposingWould:
    def test_nothing_is_proposed_or_applied(self, client):
        _as(client, "dana")
        before = _grants(client, "customer_service")

        _preview(client, "customer_service", [*before, "read:Account"])

        assert client.get("/api/roles/changes").json()["changes"] == []
        assert _grants(client, "customer_service") == before

    def test_a_change_proposing_would_refuse_is_refused_with_its_reason(self, client):
        _as(client, "dana")

        response = _preview(client, "customer_service", ["read:NoSuchType"])

        assert response.status_code == 400
        assert "NoSuchType" in response.json()["detail"]

    def test_it_is_for_manage_roles_only(self, client):
        _as(client, "cy", "customer_service")

        assert _preview(client, "customer_service", []).status_code == 403


class TestTheApproverSeesIt:
    def test_a_pending_change_carries_its_impact(self, client):
        _as(client, "dana")
        grants = [g for g in _grants(client, "customer_service") if g != "read:Customer.email"]
        client.post("/api/roles/changes", json={"role_name": "customer_service", "grants": grants},
                    headers=_csrf_headers(client))
        _as(client, "erin")

        [change] = client.get("/api/roles/changes").json()["changes"]

        assert change["impact"]["fields_lost"][0]["field"] == "email"

    def test_one_that_cannot_be_computed_is_null_not_a_failed_listing(self, client, monkeypatch):
        _as(client, "dana")
        client.post("/api/roles/changes",
                    json={"role_name": "customer_service",
                          "grants": [*_grants(client, "customer_service"), "read:Account"]},
                    headers=_csrf_headers(client))

        def broken(*_args, **_kwargs):
            raise RuntimeError("stale")

        monkeypatch.setattr("core.role_impact.role_change_impact", broken)
        response = client.get("/api/roles/changes")

        assert response.status_code == 200
        assert response.json()["changes"][0]["impact"] is None


class TestItAsksThePermissionCode:
    def test_a_label_grant_shows_as_the_fields_it_opens(self, client):
        """The proposed grants go through the SAME compilation the running
        mediators use. With label enforcement on, read:Customer.email is
        not enough -- the field carries pii -- and read:label:pii is what
        opens it. A diff of grant strings could not say that."""
        import copy

        from core.deployment_loader import access_roles, deep_freeze

        def thaw(value):
            if hasattr(value, "items"):
                return {k: thaw(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [thaw(v) for v in value]
            return value

        generation = client.app.state.generation
        # THE FIXTURE DECLARES NO LABELS, so one is declared here: email
        # carries pii.
        schema = thaw(generation.config.schema)
        schema["Customer"]["fields"]["email"]["classification"] = "pii"
        config = dataclasses.replace(generation.config, schema=deep_freeze(schema),
                                     label_enforcement=True)
        enforced = copy.copy(generation.mediator)
        enforced.schema = config.schema
        enforced.roles = access_roles(config)
        role = "customer_service"
        before = list(config.roles[role]["allowed_actions"])

        impact = role_change_impact(config, enforced, role, [*before, "read:label:pii"], 0)
        # THE CONTROL THAT MATTERS: a change unrelated to labels. The role
        # already holds read:Customer.email, demoted by the label; compared
        # uncompiled, ANY change would claim email had opened. Found when a
        # control skipping the compilation left the line above passing.
        unrelated = role_change_impact(config, enforced, role,
                                       [*before, "execute:UpdateCustomerName"], 0)

        assert {"type": "Customer", "field": "email", "from": "discover", "to": "read"} in (
            impact["fields_gained"])
        assert impact["other_gained"] == ["read:label:pii"]
        assert unrelated["fields_gained"] == []
