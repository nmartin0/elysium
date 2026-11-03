"""
The /api/v2 read surface through the real app (api/v2/).

Same fixture deployment and the same facts as test_object_sets_evaluation:
alice (us-west) sees cust_001 and cust_002 and transactions 1-4; bob
(us-east) sees cust_003 and transactions 5-6; dave (us-west) reads
Customer.name but not email or region.

These test the WIRE: that the routes are mounted behind the session, the
CSRF check and the generation pin; that denial is one 404; that errors are
problem details carrying the request id; that a page token belongs to the
caller who got it. What a set means is tested beside the mediator.
"""

import base64
import json

import pytest

from api.v2 import paging

PROBLEM = "application/problem+json"
CUSTOMERS = {"type": "base", "objectType": "Customer"}
TRANSACTIONS = {"type": "base", "objectType": "Transaction"}


def login(client, username, region="us-west", role="customer_service"):
    client.app.state.user_directory.create_user(username, "pw", region, role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def post(client, path, body):
    return client.post(f"/api/v2/{path}", json=body, headers=csrf(client))


def keys(response):
    assert response.status_code == 200, response.text
    return [row["primaryKey"] for row in response.json()["data"]]


def without_instance(problem):
    return {k: v for k, v in problem.items() if k != "errorInstanceId"}


class TestBehindTheSameDoor:
    @pytest.mark.parametrize("method, path", [
        ("get", "schema"), ("get", "objects/Customer"), ("get", "objects/Customer/cust_001"),
        ("post", "objectSets/loadObjects"), ("post", "objectSets/count"), ("post", "objectSets/aggregate"),
    ])
    def test_every_route_needs_a_session_and_says_so_as_a_problem(self, client, method, path):
        # A POST is stopped by the CSRF check before it is asked who it is
        # (as on every route); give it a matching pair so it reaches authentication.
        client.cookies.set("elysium_csrf", "t")
        response = getattr(client, method)(f"/api/v2/{path}", headers={"X-CSRF-Token": "t"})

        assert response.status_code == 401
        assert response.headers["content-type"].startswith(PROBLEM)
        body = response.json()
        assert body["errorName"] == "Unauthenticated" and body["status"] == 401
        assert body["errorInstanceId"]

    def test_a_post_without_the_csrf_token_is_refused_as_on_every_other_route(self, client):
        login(client, "v2csrf")

        response = client.post("/api/v2/objectSets/count", json={"objectSet": CUSTOMERS})

        assert response.status_code == 403

    def test_the_v1_error_shape_is_unchanged(self, client):
        response = client.get("/api/me")

        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid or expired session"}
        assert response.headers["content-type"] == "application/json"

    def test_the_spec_is_not_published(self, client):
        """Publishing /api/v2/openapi.json to signed-in callers is a later
        slice; until then there is no spec route, public or otherwise."""
        login(client, "v2spec")

        assert client.get("/openapi.json").status_code == 404
        for path in ("/api/v2/openapi.json", "/api/v2/docs", "/api/v2/redoc"):
            response = client.get(path)
            assert response.status_code == 404, path
            assert response.json()["errorName"] == "NotFound"

    def test_responses_carry_the_generation_header_and_are_not_cacheable(self, client):
        login(client, "v2hdr")

        response = client.get("/api/v2/objects/Customer")

        assert response.headers["cache-control"] == "no-store"
        assert any(name.lower().startswith("x-") and "generation" in name.lower() for name in response.headers)


class TestTheSchema:
    def test_it_is_the_callers_own_view(self, client):
        login(client, "v2schema")

        types = client.get("/api/v2/schema").json()["objectTypes"]

        assert {"Customer", "Transaction"} <= set(types)
        assert "email" in types["Customer"]["fields"]
        assert types["Customer"]["id_field"] == "customer_id" and types["Customer"]["readable"] is True

    def test_a_field_the_caller_was_not_told_about_is_not_in_it(self, client):
        login(client, "v2dave", role="customer_service_no_email")

        fields = client.get("/api/v2/schema").json()["objectTypes"]["Customer"]["fields"]

        assert "name" in fields and "email" not in fields and "region" not in fields

    def test_a_discoverable_but_withheld_field_is_marked_unreadable(self, client):
        login(client, "v2disc", role="customer_service_sees_email_exists")

        fields = client.get("/api/v2/schema").json()["objectTypes"]["Customer"]["fields"]

        assert fields["email"]["readable"] is False and fields["name"]["readable"] is True

    def test_no_storage_or_security_internals_are_served(self, client):
        login(client, "v2internals")
        text = client.get("/api/v2/schema").text

        for internal in ("primary_sql", "id_column", "customer_risk", "score_val", "silo", "via_table"):
            assert internal not in text


class TestListing:
    def test_a_list_is_the_callers_rows_with_the_title_by_default(self, client):
        login(client, "v2list")

        body = client.get("/api/v2/objects/Customer").json()

        assert body["data"] == [
            {"objectType": "Customer", "primaryKey": "cust_001", "properties": {"name": "Ada Okafor"}},
            {"objectType": "Customer", "primaryKey": "cust_002", "properties": {"name": "Bram Feldman"}}]
        assert body["totalCount"] == 2 and "nextPageToken" not in body and body["scanTruncated"] is False

    def test_select_and_order_by(self, client):
        login(client, "v2select")

        response = client.get("/api/v2/objects/Transaction?select=amount,category&orderBy=amount:desc,category")

        assert [(r["primaryKey"], r["properties"]) for r in response.json()["data"]] == [
            ("2", {"amount": 199.0, "category": "hardware"}), ("1", {"amount": 49.99, "category": "subscription"}),
            ("3", {"amount": 49.99, "category": "subscription"}), ("4", {"amount": -20.0, "category": "refund"})]

    def test_select_may_be_repeated_or_comma_separated(self, client):
        login(client, "v2repeat")

        response = client.get("/api/v2/objects/Transaction?select=amount&select=category,currency&pageSize=1")

        assert set(response.json()["data"][0]["properties"]) == {"amount", "category", "currency"}

    def test_paging_walks_every_row_once(self, client):
        login(client, "v2pages")
        seen, token = [], None
        while True:
            suffix = f"&pageToken={token}" if token else ""
            body = client.get(f"/api/v2/objects/Transaction?pageSize=3&orderBy=amount{suffix}").json()
            assert len(body["data"]) <= 3
            seen += [row["primaryKey"] for row in body["data"]]
            token = body.get("nextPageToken")
            if token is None:
                break

        assert seen == ["4", "1", "3", "2"]

    def test_the_last_page_has_no_token_and_a_full_page_does_not_invent_one(self, client):
        login(client, "v2last")

        body = client.get("/api/v2/objects/Transaction?pageSize=4").json()

        assert len(body["data"]) == 4 and "nextPageToken" not in body

    def test_a_page_size_over_the_maximum_is_clamped_not_refused(self, client):
        login(client, "v2clamp")

        assert client.get(f"/api/v2/objects/Transaction?pageSize={paging.MAX_PAGE_SIZE * 100}").status_code == 200
        assert client.get("/api/v2/objects/Transaction?pageSize=0").json()["data"][0:1] != []

    def test_a_bad_order_by_or_select_is_a_400_problem(self, client):
        login(client, "v2bad")

        for query in ("orderBy=amount:sideways", "orderBy=reverse_link_nope", "select=nonexistent_field"):
            response = client.get(f"/api/v2/objects/Customer?{query}")
            assert response.status_code == 400
            assert response.headers["content-type"].startswith(PROBLEM)
            assert response.json()["errorName"] == "InvalidArgument"

    def test_a_page_beyond_the_end_is_empty_not_an_error(self, client):
        login(client, "v2beyond")
        token = client.get("/api/v2/objects/Transaction?pageSize=1").json()["nextPageToken"]

        # Rows vanish between pages; the token's position is now past the end.
        body = client.get(f"/api/v2/objects/Transaction?pageSize=1&pageToken={token}").json()
        assert len(body["data"]) == 1


class TestPageTokens:
    def first_token(self, client, path="/api/v2/objects/Transaction?pageSize=1"):
        response = client.get(path)
        return response.json()["nextPageToken"]

    def test_another_user_cannot_use_my_token(self, client):
        login(client, "v2tok_a")
        token = self.first_token(client)
        login(client, "v2tok_b")

        response = client.get(f"/api/v2/objects/Transaction?pageSize=1&pageToken={token}")

        assert response.status_code == 400
        assert response.json()["errorName"] == "InvalidPageToken"

    def test_every_way_a_token_can_be_wrong_looks_the_same(self, client):
        login(client, "v2tok_same")
        token = self.first_token(client)
        payload, _, signature = token.partition(".")
        forged = base64.urlsafe_b64encode(json.dumps({"o": 0, "e": 9_999_999_999}).encode()).decode().rstrip("=")
        responses = [
            client.get(f"/api/v2/objects/Transaction?pageSize=1&pageToken={bad}")
            for bad in (f"{forged}.{signature}", "garbage", f"{payload}.", token[:-3] + "AAA")]
        # a token from a different query
        responses.append(client.get(f"/api/v2/objects/Transaction?pageSize=1&orderBy=amount&pageToken={token}"))
        responses.append(client.get(f"/api/v2/objects/Transaction?pageSize=1&select=amount&pageToken={token}"))
        responses.append(client.get(f"/api/v2/objects/Customer?pageSize=1&pageToken={token}"))

        assert {response.status_code for response in responses} == {400}
        assert len({json.dumps(without_instance(r.json()), sort_keys=True) for r in responses}) == 1

    def test_a_token_that_is_not_ascii_is_the_same_refusal_not_a_fault(self, client):
        login(client, "v2tok_utf8")
        token = self.first_token(client)
        plain = client.get("/api/v2/objects/Transaction?pageSize=1&pageToken=garbage")

        for bad in ("abc.%C3%A9", f"{token}%C3%A9", "%C3%A9.%C3%A9"):
            response = client.get(f"/api/v2/objects/Transaction?pageSize=1&pageToken={bad}")
            assert response.status_code == 400, bad
            assert without_instance(response.json()) == without_instance(plain.json())

    def test_an_expired_token_is_refused(self, client, monkeypatch):
        login(client, "v2tok_old")
        token = self.first_token(client)
        real = paging.time.time
        monkeypatch.setattr(paging.time, "time", lambda: real() + paging.TOKEN_LIFETIME_SECONDS + 5)

        assert client.get(f"/api/v2/objects/Transaction?pageSize=1&pageToken={token}").status_code == 400

    def test_a_token_holds_no_row_data(self, client):
        login(client, "v2tok_data")
        token = self.first_token(client)
        payload = token.partition(".")[0]

        held = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))

        assert set(held) == {"o", "e"}
        assert "v2tok_data" not in token

    def test_the_set_posted_for_load_objects_binds_its_tokens_too(self, client):
        login(client, "v2tok_post")
        first = post(client, "objectSets/loadObjects", {"objectSet": TRANSACTIONS, "pageSize": 1}).json()

        again = post(client, "objectSets/loadObjects",
                     {"objectSet": TRANSACTIONS, "pageSize": 1, "pageToken": first["nextPageToken"]})
        other = post(client, "objectSets/loadObjects",
                     {"objectSet": {"type": "filter", "objectSet": TRANSACTIONS,
                                    "where": {"type": "gt", "field": "amount", "value": 0}},
                      "pageSize": 1, "pageToken": first["nextPageToken"]})

        assert again.status_code == 200 and keys(again) == ["2"]
        assert other.status_code == 400 and other.json()["errorName"] == "InvalidPageToken"


class TestOneObject:
    def test_it_returns_every_readable_field(self, client):
        login(client, "v2one")

        body = client.get("/api/v2/objects/Customer/cust_001").json()

        assert body["primaryKey"] == "cust_001" and body["objectType"] == "Customer"
        assert body["properties"]["name"] == "Ada Okafor" and body["properties"]["email"] == "ada.okafor@example.com"

    def test_select_narrows_it(self, client):
        login(client, "v2onesel")

        assert client.get("/api/v2/objects/Customer/cust_001?select=name").json()["properties"] == {
            "name": "Ada Okafor"}

    def test_unknown_hidden_and_denied_are_one_404_in_the_same_words(self, client):
        login(client, "v2deny")
        responses = [client.get(path) for path in (
            "/api/v2/objects/Customer/cust_999",   # no such key
            "/api/v2/objects/Customer/cust_003",   # exists; not alice's region
            "/api/v2/objects/Customer/cust_004",   # exists; not alice's region
            "/api/v2/objects/NoSuchType/cust_001",  # no such type
            "/api/v2/objects/NoSuchType",
            "/api/v2/nowhere")]

        assert {r.status_code for r in responses} == {404}
        assert {r.headers["content-type"] for r in responses} == {"application/problem+json"}
        assert len({json.dumps(without_instance(r.json()), sort_keys=True) for r in responses}) == 1
        assert responses[0].json()["errorName"] == "NotFound"

    def test_the_other_regions_customer_is_reachable_by_the_other_user_only(self, client):
        login(client, "v2bob", region="us-east")

        assert client.get("/api/v2/objects/Customer/cust_003").status_code == 200
        assert client.get("/api/v2/objects/Customer/cust_001").status_code == 404

    def test_a_type_with_no_read_grant_is_the_same_404_as_an_unknown_one(self, client):
        login(client, "v2ed", role="editor")  # reads Customer, and nothing of Transaction

        assert client.get("/api/v2/objects/Transaction").status_code == 404
        assert client.get("/api/v2/objects/Transaction/1").status_code == 404
        assert client.get("/api/v2/objects/Customer/cust_001").status_code == 200

    def test_a_withheld_field_cannot_be_selected_and_is_the_same_400_as_a_missing_one(self, client):
        login(client, "v2sel", role="customer_service_no_email")

        hidden = client.get("/api/v2/objects/Customer/cust_001?select=email")
        absent = client.get("/api/v2/objects/Customer/cust_001?select=zzz_missing")
        listing = client.get("/api/v2/objects/Customer?select=email")

        assert hidden.status_code == absent.status_code == listing.status_code == 400
        assert hidden.json()["detail"].replace("email", "F") == absent.json()["detail"].replace("zzz_missing", "F")
        # and a bad select is refused whether or not the key exists
        assert client.get("/api/v2/objects/Customer/cust_999?select=email").status_code == 400
        assert client.get("/api/v2/objects/Customer/cust_001?select=name").json()["properties"] == {
            "name": "Ada Okafor"}


class TestObjectSets:
    def test_load_objects_for_a_composed_set(self, client):
        login(client, "v2load")
        body = {"objectSet": {"type": "searchAround", "link": "transactions", "objectSet": {
                    "type": "filter", "objectSet": CUSTOMERS, "where": {"type": "eq", "field": "name",
                                                                        "value": "Ada Okafor"}}},
                "select": ["amount"], "orderBy": [{"field": "amount", "direction": "desc"}]}

        response = post(client, "objectSets/loadObjects", body)

        assert [(r["primaryKey"], r["properties"]) for r in response.json()["data"]] == [
            ("2", {"amount": 199.0}), ("1", {"amount": 49.99})]
        assert response.json()["totalCount"] == 2

    def test_a_hidden_row_never_appears_however_it_is_asked_for(self, client):
        login(client, "v2hidden")
        for object_set in (
                {"type": "static", "objectType": "Customer", "primaryKeys": ["cust_003", "cust_004"]},
                {"type": "filter", "objectSet": CUSTOMERS, "where": {"type": "eq", "field": "region",
                                                                     "value": "us-east"}},
                {"type": "subtract", "objectSets": [
                    {"type": "static", "objectType": "Customer", "primaryKeys": ["cust_003"]},
                    {"type": "static", "objectType": "Customer", "primaryKeys": ["cust_999"]}]},
                {"type": "searchAround", "link": "transactions", "objectSet": {
                    "type": "static", "objectType": "Customer", "primaryKeys": ["cust_003"]}}):
            assert keys(post(client, "objectSets/loadObjects", {"objectSet": object_set})) == []
            assert post(client, "objectSets/count", {"objectSet": object_set}).json()["count"] == 0

    def test_count_matches_what_load_returns(self, client):
        login(client, "v2count")

        assert post(client, "objectSets/count", {"objectSet": TRANSACTIONS}).json()["count"] == 4
        assert post(client, "objectSets/count", {"objectSet": {
            "type": "filter", "objectSet": TRANSACTIONS,
            "where": {"type": "lt", "field": "amount", "value": 100}}}).json()["count"] == 3

    def test_aggregate(self, client):
        login(client, "v2agg")

        response = post(client, "objectSets/aggregate", {
            "objectSet": TRANSACTIONS, "groupBy": [{"field": "category"}],
            "metrics": [{"type": "sum", "field": "amount", "name": "total"}, {"type": "count"}]})

        assert response.status_code == 200
        assert response.json()["data"] == [
            {"group": {"category": "subscription"}, "metrics": {"total": 99.98, "count": 2}},
            {"group": {"category": "hardware"}, "metrics": {"total": 199.0, "count": 1}},
            {"group": {"category": "refund"}, "metrics": {"total": -20.0, "count": 1}}]

    def test_aggregate_without_a_grouping_is_one_row(self, client):
        login(client, "v2agg1")

        data = post(client, "objectSets/aggregate", {
            "objectSet": TRANSACTIONS, "metrics": [{"type": "min", "field": "amount", "name": "low"},
                                                   {"type": "max", "field": "amount", "name": "high"},
                                                   {"type": "avg", "field": "amount", "name": "mean"}]}).json()["data"]

        assert data == [{"group": {}, "metrics": {"low": -20.0, "high": 199.0, "mean": pytest.approx(69.745)}}]

    def test_aggregate_counts_only_what_the_caller_can_see(self, client):
        login(client, "v2aggbob", region="us-east")

        data = post(client, "objectSets/aggregate", {"objectSet": TRANSACTIONS,
                                                     "metrics": [{"type": "count"}]}).json()["data"]

        assert data == [{"group": {}, "metrics": {"count": 2}}]

    def test_aggregate_is_refused_for_what_it_does_not_cover(self, client):
        login(client, "v2aggno")

        for body, words in (
                ({"groupBy": [{"field": "category"}, {"field": "currency"}], "metrics": [{"type": "count"}]},
                 "one field"),
                ({"groupBy": [{"type": "ranges", "field": "amount"}], "metrics": [{"type": "count"}]}, "exact"),
                ({"metrics": [{"type": "sum", "field": "category"}]}, "numeric"),
                ({"metrics": [{"type": "median", "field": "amount"}]}, "Unknown metric"),
                ({"metrics": [{"type": "sum", "field": "nonexistent_field"}]}, "Unknown field")):
            response = post(client, "objectSets/aggregate", {"objectSet": TRANSACTIONS, **body})
            assert response.status_code == 400 and words in response.json()["detail"], response.text

    def test_a_withheld_field_is_refused_for_filter_sort_and_metric_alike(self, client):
        login(client, "v2withheld", role="customer_service_no_email")
        bad = {"filter": {"objectSet": {"type": "filter", "objectSet": CUSTOMERS,
                                        "where": {"type": "eq", "field": "email", "value": "x"}}},
               "sort": {"objectSet": CUSTOMERS, "orderBy": [{"field": "email"}]},
               "select": {"objectSet": CUSTOMERS, "select": ["email"]}}
        absent = {"filter": {"objectSet": {"type": "filter", "objectSet": CUSTOMERS,
                                           "where": {"type": "eq", "field": "zzz", "value": "x"}}},
                  "sort": {"objectSet": CUSTOMERS, "orderBy": [{"field": "zzz"}]},
                  "select": {"objectSet": CUSTOMERS, "select": ["zzz"]}}

        for kind in bad:
            hidden, missing = post(client, "objectSets/loadObjects", bad[kind]), post(
                client, "objectSets/loadObjects", absent[kind])
            assert hidden.status_code == missing.status_code == 400
            assert hidden.json()["detail"].replace("email", "F") == missing.json()["detail"].replace("zzz", "F")
            assert hidden.json()["errorName"] == missing.json()["errorName"] == "InvalidArgument"

    def test_bad_requests_are_problems(self, client):
        login(client, "v2badreq")
        cases = [
            ({"objectSet": {"type": "reference", "id": "x"}}, "Unknown object set type"),
            ({"objectSet": {"type": "similarTo", "objectType": "Customer"}}, "Unknown object set type"),
            ({"objectSet": {"type": "filter", "objectSet": CUSTOMERS, "where": {"type": "like"}}}, "Unknown filter"),
            ({"objectSet": {"type": "base"}}, "objectType"),
            ({"objectSet": CUSTOMERS, "pageSize": "many"}, None),
            ({"objectSet": CUSTOMERS, "surprise": 1}, None),
            ({}, None),
        ]
        for body, words in cases:
            response = post(client, "objectSets/loadObjects", body)
            assert response.status_code == 400, body
            assert response.headers["content-type"].startswith(PROBLEM)
            problem = response.json()
            assert {"type", "title", "status", "detail", "errorName", "errorInstanceId", "parameters"} <= set(problem)
            if words:
                assert words in problem["detail"]

    def test_the_depth_cap_is_a_400(self, client):
        login(client, "v2deep")
        from core.ontology.object_sets import MAX_SET_DEPTH

        node = CUSTOMERS
        for _ in range(MAX_SET_DEPTH):
            node = {"type": "union", "objectSets": [node, CUSTOMERS]}

        response = post(client, "objectSets/count", {"objectSet": node})

        assert response.status_code == 400 and "deep" in response.json()["detail"]

    def test_an_unknown_or_ungranted_type_in_a_set_is_the_same_404(self, client):
        login(client, "v2settype", role="editor")

        responses = [post(client, "objectSets/count", {"objectSet": {"type": "base", "objectType": name}})
                     for name in ("Transaction", "NoSuchType")]

        assert {r.status_code for r in responses} == {404}
        assert len({json.dumps(without_instance(r.json()), sort_keys=True) for r in responses}) == 1


class TestWhatAnErrorMayReveal:
    """Nothing the mediator says reaches the caller, and a hidden link or a
    storage layout is never the subject of a sentence."""

    @pytest.fixture
    def mediator(self, client):
        return client.app.state.generation.mediator

    def test_a_link_to_a_type_the_caller_cannot_read_is_an_unknown_field_everywhere(self, client, mediator,
                                                                                  monkeypatch):
        import types

        grants = frozenset({"read:Transaction", "read:Transaction.transaction_id", "read:Transaction.amount",
                            "read:Transaction.customer_id"})
        roles = dict(mediator.roles)
        # The user directory knows the fixture's roles, so the role the user
        # is created with is re-granted for this test.
        roles["editor"] = types.MappingProxyType({**mediator.roles["editor"], "allowed_actions": grants})
        monkeypatch.setattr(mediator, "roles", types.MappingProxyType(roles))
        login(client, "v2hiddenlink", role="editor")
        filtered = {"objectSet": {"type": "filter", "objectSet": TRANSACTIONS, "where": {
            "type": "eq", "field": "customer_id", "value": "cust_001"}}}

        def asked(path, body):
            return post(client, path, body)

        for field_name in ("customer_id", "nonexistent_field"):
            responses = [
                asked("objectSets/loadObjects", {"objectSet": TRANSACTIONS, "orderBy": [{"field": field_name}]}),
                asked("objectSets/count", {"objectSet": {**filtered["objectSet"], "where": {
                    "type": "startsWith", "field": field_name, "value": "cust_001"}}}),
                asked("objectSets/aggregate", {"objectSet": TRANSACTIONS, "groupBy": [{"field": field_name}],
                                               "metrics": [{"type": "count"}]}),
                asked("objectSets/aggregate", {"objectSet": TRANSACTIONS,
                                               "metrics": [{"type": "sum", "field": field_name}]})]
            assert {r.status_code for r in responses} == {400}, [r.text for r in responses]
            assert all("Unknown field" in r.json()["detail"] and "link" not in r.json()["detail"]
                       for r in responses)
            if field_name == "customer_id":
                shown = [r.json()["detail"].replace("customer_id", "F") for r in responses]
            else:
                assert shown == [r.json()["detail"].replace(field_name, "F") for r in responses]

    def test_fields_of_two_storages_are_one_400_on_load_count_and_aggregate(self, client, mediator, monkeypatch):
        monkeypatch.setitem(mediator.schema["Customer"]["fields"]["risk_score"], "storage", "risk_db")
        login(client, "v2storages")
        both = {"type": "and", "value": [{"type": "eq", "field": "name", "value": "x"},
                                         {"type": "gt", "field": "risk_score", "value": 1}]}
        filtered = {"type": "filter", "objectSet": CUSTOMERS, "where": both}

        responses = [
            post(client, "objectSets/loadObjects", {"objectSet": filtered}),
            post(client, "objectSets/count", {"objectSet": filtered}),
            post(client, "objectSets/loadObjects", {"objectSet": CUSTOMERS,
                                                    "orderBy": [{"field": "name"}, {"field": "risk_score"}]}),
            post(client, "objectSets/aggregate", {"objectSet": CUSTOMERS, "groupBy": [{"field": "name"}],
                                                  "metrics": [{"type": "sum", "field": "risk_score"}]})]

        assert [r.status_code for r in responses] == [400] * 4, [r.text for r in responses]
        assert {r.json()["detail"] for r in responses} == {"These fields cannot be combined in one request."}

    def test_a_mediator_refusal_nobody_foresaw_is_a_fixed_400_never_its_words(self, client, mediator, monkeypatch):
        def refuse(*args, **kwargs):
            raise ValueError("group_by 'customer_id' is a link on Transaction; silo primary_sql")

        monkeypatch.setattr(mediator, "aggregate_measures", refuse)
        login(client, "v2foreseen")

        # Only the aggregation refuses here, so the answer is the aggregate
        # route's own handling and not the shared one's.
        aggregate = post(client, "objectSets/aggregate", {"objectSet": TRANSACTIONS, "metrics": [{"type": "count"}]})
        monkeypatch.setattr(mediator, "search_object", refuse)
        loaded = post(client, "objectSets/loadObjects", {"objectSet": TRANSACTIONS})
        counted = post(client, "objectSets/count", {"objectSet": TRANSACTIONS})

        for response in (aggregate, loaded, counted):
            assert response.status_code == 400
            assert response.json()["detail"] == "This request could not be evaluated."
            assert "link" not in response.text and "primary_sql" not in response.text

    def test_a_request_that_reads_too_many_objects_is_refused_not_cut_short(self, client, monkeypatch):
        from core.ontology import object_sets as sets

        monkeypatch.setattr(sets, "MAX_SCANNED_ROWS", 5)
        login(client, "v2scanned")
        twice = {"type": "union", "objectSets": [TRANSACTIONS, TRANSACTIONS]}

        for path in ("objectSets/loadObjects", "objectSets/count"):
            response = post(client, path, {"objectSet": twice})
            assert response.status_code == 400 and "more than 5 objects" in response.json()["detail"], path
        assert post(client, "objectSets/count", {"objectSet": TRANSACTIONS}).json()["count"] == 4


class TestErrorsAndTheRequestId:
    def test_the_instance_id_of_a_success_names_a_readable_trace(self, client):
        login(client, "v2trace")

        body = client.get("/api/v2/objects/Customer/cust_001").json()
        trace = client.get(f"/api/requests/{body['requestId']}/trace")

        assert trace.status_code == 200 and trace.json()

    def test_the_error_instance_id_is_the_request_id_the_call_was_given(self, client, monkeypatch):
        from core.request_context import RequestContext

        fixed = RequestContext(request_id="req-fixed-0001")
        monkeypatch.setattr(RequestContext, "new", classmethod(lambda cls, deadline_seconds=None: fixed))

        unauthenticated = client.get("/api/v2/objects/Customer")
        login(client, "v2fixed")
        refused = client.get("/api/v2/objects/NoSuchType")
        served = client.get("/api/v2/objects/Customer/cust_001")
        invalid = post(client, "objectSets/count", {"objectSet": {"type": "base"}})

        assert unauthenticated.json()["errorInstanceId"] == "req-fixed-0001"
        assert refused.json()["errorInstanceId"] == "req-fixed-0001"
        assert invalid.json()["errorInstanceId"] == "req-fixed-0001"
        assert served.json()["requestId"] == "req-fixed-0001"

    def test_each_error_carries_a_fresh_instance_id(self, client):
        login(client, "v2ids")

        first, second = client.get("/api/v2/nowhere").json(), client.get("/api/v2/nowhere").json()

        assert first["errorInstanceId"] != second["errorInstanceId"]
        assert first["type"] == "/api/v2/problems/NotFound" and first["title"] == "Not found"
        assert first["status"] == 404 and first["parameters"] == {}

    def test_a_validation_failure_names_where_and_never_the_value_sent(self, client):
        login(client, "v2valid")

        response = post(client, "objectSets/count", {"objectSet": "secret-looking-value"})

        assert response.status_code == 400
        assert "secret-looking-value" not in response.text
        assert response.json()["parameters"]["errors"][0]["location"][-1] == "objectSet"
