"""
The cleaning-rule review queue over HTTP (R31).

Gated on manage:deployment, and narrowed by field: a suggestion carries
values from its field, so an administrator who may not read that field
is not shown it -- and cannot decide it.
"""

from core.rule_suggestions import ABSENCE, RuleSuggestionStore, suggestion_id
from tests.conftest import with_roles

SID = suggestion_id("Customer", "email", ABSENCE, "N/A")


def _seed(client):
    store = RuleSuggestionStore(client.app.state.runtime_paths.data_dir / "rule_suggestions.db")
    store.record_scan([{"object_type": "Customer", "field": "email", "kind": ABSENCE,
                        "value": "N/A", "seen": 4, "why": "a word meaning 'no value'",
                        "examples": ["N/A"]}], set())


def _as(client, name, grants):
    with_roles(client.app, **{name: {"allowed_actions": grants}})
    client.app.state.user_directory.create_user(name, "pw-for-tests", "us-west", name)
    assert client.post("/api/login", json={"username": name,
                                           "password": "pw-for-tests"}).status_code == 204


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def test_it_lists_with_the_yaml_to_add(client):
    _seed(client)
    _as(client, "cleaner", ["manage:deployment", "read:Customer", "read:Customer.email"])

    (item,) = client.get("/api/admin/rule-suggestions").json()

    assert (item["field"], item["value"], item["state"]) == ("email", "N/A", "pending")
    assert 'null_if: ["N/A"]' in item["yaml"]


def test_without_manage_deployment_it_is_refused(client):
    _as(client, "reader", ["read:Customer", "read:Customer.email"])

    assert client.get("/api/admin/rule-suggestions").status_code == 403


def test_a_field_the_caller_cannot_read_is_not_shown_nor_decidable(client):
    _seed(client)
    _as(client, "blind", ["manage:deployment", "read:Customer"])

    assert client.get("/api/admin/rule-suggestions").json() == []
    response = client.post(f"/api/admin/rule-suggestions/{SID}/decide",
                           json={"decision": "dismissed"}, headers=_csrf(client))
    assert response.status_code == 404


def test_dismissing_is_recorded_and_hides_the_yaml(client):
    _seed(client)
    _as(client, "cleaner", ["manage:deployment", "read:Customer", "read:Customer.email"])

    response = client.post(f"/api/admin/rule-suggestions/{SID}/decide",
                           json={"decision": "dismissed"}, headers=_csrf(client))

    assert response.status_code == 204
    (item,) = client.get("/api/admin/rule-suggestions").json()
    assert (item["state"], item["decided_by"], item["yaml"]) == ("dismissed", "cleaner", None)
