"""
A count and an aggregate describe the set the search box describes.

SEEN IN A BROWSER, NOT INFERRED. Browse's subject read "Transaction ·
81" for the search "refund", and beside it the category donut drew all
five categories and the facets counted 404. The table ran the text
through search_object_free_text -- whose own docstring says it "is what
makes charts and a table describe ONE object set" -- and the count and
aggregate routes took conditions only. The charts panel even received
the text as a prop, documented "so charts describe the same object set
the table does", and never sent it.

THE FIXTURE: Ada Okafor (cust_001) and Bram Feldman (cust_002) are
us-west, which is the reader's compartment; the text "Ada" matches one
of them.
"""


def _login(client, username):
    client.app.state.user_directory.create_user(username, "pw", "us-west", "customer_service")
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _post(client, path, body):
    return client.post(path, json=body, headers={"X-CSRF-Token": client.cookies.get("elysium_csrf")})


class TestTheTextNarrowsTheNumbers:
    def test_a_count_with_text_counts_what_the_search_finds(self, client):
        _login(client, "t1")

        searched = client.get("/api/objects/Customer/search", params={"q": "Ada"}).json()
        counted = _post(client, "/api/objects/Customer/count", {"criteria": {}, "q": "Ada"}).json()

        assert counted["count"] == searched["total_matches"] == 1

    def test_an_aggregate_with_text_aggregates_what_the_search_finds(self, client):
        _login(client, "t2")

        grouped = _post(client, "/api/objects/Customer/aggregate",
                        {"criteria": {}, "measures": [{"name": "n", "aggregate": "count"}],
                         "group_by": "region", "q": "Ada"}).json()

        assert grouped["rows"] == [{"group": {"region": "us-west"}, "metrics": {"n": 1}}]

    def test_without_text_nothing_changes(self, client):
        """THE CONTROL. A text query that leaked into ordinary requests
        -- or an empty one treated as "match nothing" -- would pass the
        two tests above."""
        _login(client, "t3")

        counted = _post(client, "/api/objects/Customer/count", {"criteria": {}}).json()
        blank = _post(client, "/api/objects/Customer/count", {"criteria": {}, "q": "   "}).json()

        assert counted["count"] == blank["count"] == 2

    def test_text_and_conditions_both_narrow(self, client):
        """The two contexts AND, as the search's own docstring says --
        the text decides what MATCHES, the conditions what is ELIGIBLE."""
        _login(client, "t4")

        none = _post(client, "/api/objects/Customer/count", {
            "q": "Ada",
            "conditions": [{"field": "name", "operator": "equals", "value": "Bram Feldman"}],
        }).json()

        assert none["count"] == 0

    def test_text_never_reaches_past_the_compartment(self, client):
        """Chidi Nwosu is us-east. Searching his name as a us-west
        reader counts nothing, exactly as the table finds nothing."""
        _login(client, "t5")

        counted = _post(client, "/api/objects/Customer/count", {"criteria": {}, "q": "Chidi"}).json()

        assert counted["count"] == 0
