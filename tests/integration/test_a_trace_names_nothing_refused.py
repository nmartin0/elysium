"""
GET /api/requests/{id}/trace is the caller's own record of one request, and it
must never become a way to read what they were refused.

THE DEFECT. check_access() writes one audit line per DENIED object, naming
its id, and the trace reader returned them. So a scan over a type recorded
every hidden row it touched, a static set of guessed ids recorded the ones
that exist, and a filter on a link recorded its hidden targets -- all
readable back by the caller who made the request, on v1 routes as much as v2.

THE RULE, in the reader (api/routes.py only maps what the reader returns):
the trace holds what the caller was GRANTED and no refusal in any form (a
refusal by the grants alone, kept without its id, still showed which guess
touched something, by its presence, its order and its flags); no record
carries mac_allowed or rbac_allowed; a bulk-read record is returned only
when it granted something and carries no count of what was denied or
considered. The full lines stay in the audit log file.
"""

import json

from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.object_sets import SchemaView, evaluate, parse_object_set, prepare
from core.request_context import RequestContext

HIDDEN_CUSTOMERS = {"cust_003", "cust_004"}
HIDDEN_TRANSACTIONS = {"5", "6", "7"}


def login(client, username):
    client.app.state.user_directory.create_user(username, "pw", "us-west", "customer_service")
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def named(entries):
    return {str(e["object_id"]) for e in entries if e.get("object_id") is not None}


class TestTheReader:
    def log(self, tmp_path):
        audit = AuditLog(log_path=tmp_path / "audit.log")
        audit.log_access("alice", "Customer", "cust_001", "read:Customer", True, True, request_id="r")
        audit.log_access("alice", "Customer", "cust_003", "read:Customer", False, True, request_id="r")
        audit.log_access("alice", "Customer", "cust_001", "read:Customer.email", True, False, request_id="r")
        audit.log_access("alice", "Customer", None, "read:Customer", None, False, request_id="r")
        audit.log_bulk_read("alice", "Customer", "read:Customer", considered=4, denied_object_ids=["cust_003"],
                            fields_read=[], security_values_seen={"us-west"}, request_id="r")
        audit.log_unknown_reference("alice", "Customer", "nonexistent")
        return audit

    def test_a_refusal_by_the_row_check_is_not_shown(self, tmp_path):
        shown = self.log(tmp_path).entries_for_request("r", "alice")

        assert "cust_003" not in named(shown)
        assert not [e for e in shown if e.get("mac_allowed") is False]

    def test_a_refusal_by_the_grants_alone_is_not_shown_either(self, tmp_path):
        shown = self.log(tmp_path).entries_for_request("r", "alice")

        assert not [e for e in shown if e.get("action") == "read:Customer.email"]
        assert not [e for e in shown if e.get("action") == "read:Customer" and e.get("object_id") is None
                    and e.get("stage") != "bulk_read"]

    def test_no_record_carries_the_flags(self, tmp_path):
        shown = self.log(tmp_path).entries_for_request("r", "alice")

        assert shown and not [e for e in shown if {"mac_allowed", "rbac_allowed"} & set(e)]

    def test_a_bulk_read_that_granted_nothing_is_not_returned(self, tmp_path):
        audit = AuditLog(log_path=tmp_path / "audit.log")
        audit.log_bulk_read("alice", "Customer", "read:Customer", considered=3,
                            denied_object_ids=["a", "b", "c"], fields_read=[],
                            security_values_seen=set(), request_id="r")

        assert audit.entries_for_request("r", "alice") == []

    def test_a_grant_keeps_its_id(self, tmp_path):
        shown = self.log(tmp_path).entries_for_request("r", "alice")

        assert [e["object_id"] for e in shown if e.get("action") == "read:Customer"
                and e.get("stage") == "access_check"] == ["cust_001"]

    def test_a_bulk_record_counts_nothing_hidden(self, tmp_path):
        shown = self.log(tmp_path).entries_for_request("r", "alice")

        bulk = [e for e in shown if e.get("stage") == "bulk_read"]
        assert len(bulk) == 1  # it granted one object of its four
        assert not {"denied", "denied_object_ids", "considered"} & set(bulk[0])
        assert "cust_003" not in json.dumps(shown)

    def test_a_record_of_any_other_stage_is_not_returned(self, tmp_path):
        """security_resolution_failed names the object it could not resolve,
        which is a hidden one."""
        audit = self.log(tmp_path)
        with open(tmp_path / "audit.log", "a") as handle:
            handle.write(json.dumps({"stage": "security_resolution_failed", "user_id": "alice",
                                     "request_id": "r", "object_type": "Customer",
                                     "object_id": "cust_004"}) + "\n")

        shown = audit.entries_for_request("r", "alice")

        assert "cust_004" not in json.dumps(shown)

    def test_the_full_lines_stay_in_the_audit_log(self, tmp_path):
        self.log(tmp_path)
        text = (tmp_path / "audit.log").read_text()

        assert "cust_003" in text and '"denied_object_ids"' in text


class TestEveryWayOfTouchingAHiddenRowLeavesNoNameInTheTrace:
    def alice(self, deployment):
        return resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)

    def traced(self, mediator, user, raw):
        context = RequestContext.new()
        view = SchemaView(mediator, user)
        evaluate(mediator, user, prepare(parse_object_set(raw), view), view, context)
        return mediator.audit_log.entries_for_request(context.request_id, user.user_id)

    def test_a_scan_of_a_type(self, mediator, deployment):
        shown = self.traced(mediator, self.alice(deployment), {"type": "base", "objectType": "Transaction"})

        assert not named(shown) & HIDDEN_TRANSACTIONS

    def test_a_static_set_of_guessed_ids(self, mediator, deployment):
        shown = self.traced(mediator, self.alice(deployment), {
            "type": "static", "objectType": "Transaction", "primaryKeys": ["5", "6", "999"]})

        assert not named(shown) & HIDDEN_TRANSACTIONS

    def test_a_filter_on_a_hidden_link(self, mediator, deployment, monkeypatch):
        monkeypatch.setitem(mediator.schema["Transaction"], "security", {"unrestricted": True})
        shown = self.traced(mediator, self.alice(deployment), {
            "type": "filter", "objectSet": {"type": "base", "objectType": "Transaction"},
            "where": {"type": "isNull", "field": "customer_id", "value": True}})

        assert not named(shown) & (HIDDEN_CUSTOMERS | HIDDEN_TRANSACTIONS)
        assert "cust_003" not in json.dumps(shown) and "cust_004" not in json.dumps(shown)

    def test_a_v1_get_of_a_hidden_row(self, mediator, deployment):
        user = self.alice(deployment)
        context = RequestContext.new()

        assert mediator.get_field(user, "Customer", "cust_003", "name", context=context) is None
        shown = mediator.audit_log.entries_for_request(context.request_id, user.user_id)

        assert not named(shown) & HIDDEN_CUSTOMERS

    def test_a_v1_search_of_a_type(self, mediator, deployment):
        user = self.alice(deployment)
        context = RequestContext.new()

        mediator.search_object(user, "Transaction", [], context=context)
        shown = mediator.audit_log.entries_for_request(context.request_id, user.user_id)

        assert not named(shown) & HIDDEN_TRANSACTIONS


class TestThroughTheRoute:
    def trace(self, client, request_id):
        response = client.get(f"/api/requests/{request_id}/trace")
        assert response.status_code == 200
        return response.json()

    def test_a_v1_search_and_a_v1_get_of_a_hidden_row(self, client):
        login(client, "tracer1")

        search = client.get("/api/objects/Transaction/search?q=").json()["request_id"]
        detail = client.get("/api/objects/Customer/cust_003")
        shown = self.trace(client, search)

        assert not named(shown) & HIDDEN_TRANSACTIONS
        assert not [e for e in shown if {"mac_allowed", "rbac_allowed"} & set(e)]
        if detail.status_code == 200 and detail.json().get("request_id"):
            assert not named(self.trace(client, detail.json()["request_id"])) & HIDDEN_CUSTOMERS

    def test_a_v2_load_of_a_hidden_set(self, client):
        login(client, "tracer2")

        body = client.post("/api/v2/objectSets/loadObjects", headers=csrf(client), json={
            "objectSet": {"type": "base", "objectType": "Transaction"}}).json()
        shown = self.trace(client, body["requestId"])

        assert not named(shown) & HIDDEN_TRANSACTIONS
        assert shown, "the grants and the bulk read are still shown"


class TestARefusalOnALinkLeavesNoSignInTheTrace:
    """A role that reads Transaction but not Customer: the trace of reading
    each transaction's customer_id must be the same whatever the link holds."""

    def test_the_trace_of_a_masked_link_read_has_no_refusal_and_no_flag(self, mediator, deployment, monkeypatch):
        import types

        alice = resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)
        role = dict(mediator.roles[alice.role_name])
        role["allowed_actions"] = frozenset(a for a in role["allowed_actions"] if not a.startswith("read:Customer"))
        roles = dict(mediator.roles)
        roles[alice.role_name] = types.MappingProxyType(role)
        monkeypatch.setattr(mediator, "roles", types.MappingProxyType(roles))
        context = RequestContext.new()

        for transaction in mediator.search_object(alice, "Transaction", [], context=context):
            assert mediator.get_field(alice, "Transaction", transaction, "customer_id", context) is None
        shown = mediator.audit_log.entries_for_request(context.request_id, alice.user_id)

        assert shown, "the grants on Transaction are still shown"
        assert not [e for e in shown if e.get("object_type") == "Customer"]
        assert not [e for e in shown if {"mac_allowed", "rbac_allowed"} & set(e)]
