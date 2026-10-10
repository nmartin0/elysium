"""
Saved views, where something scheduled can reach them.

WHY THEY MOVED. A SavedView was `{name, url}` in the browser's
localStorage -- perfect for a person returning to a search, invisible
to everything else. A condition that runs after a sync cannot read a
browser.

A STORED QUERY, NOT A URL. The URL carried type, q, sort, view and
filters; only the first, second and last describe WHAT MATCHES. The
others describe how a person likes to look at it.

PRIVATE TO THEIR OWNER, AND THAT IS NOT A LIMITATION. A query can name
specific ids -- "customer_id = cust_001" says cust_001 exists -- which
is the leak shape that deferred the Query panel's starters. A
condition still works across recipients, because a recipient sees the
condition's DESCRIPTION and their own count, never the query.
"""

from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


def _as(client, username, role="customer_service"):
    client.app.state.user_directory.create_user(
        username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _save(client, name, object_type="Customer", **extra):
    return client.post(
        "/api/saved-views",
        json={"name": name, "object_type": object_type, **extra},
        headers=_csrf_headers(client),
    )


class TestSavingAndListing:
    def test_a_saved_view_comes_back(self, client):
        _as(client, "alice")
        _save(client, "My customers")

        views = client.get("/api/saved-views").json()["views"]

        assert [v["name"] for v in views] == ["My customers"]

    def test_filters_survive_the_round_trip(self, client):
        """THE FILTERS ARE THE QUERY. A view that forgot them would
        match everything, which is the failure that looks like
        working."""
        _as(client, "alice")
        # `amount` IS A Transaction FIELD, and this was a Customer
        # view. The original passed because the route returned stored
        # conditions VERBATIM -- a condition that could never have run
        # came back looking live.
        #
        # WIRED-1 re-authorises at read time, so a filter now has to
        # name a field the type actually has and the caller may read.
        _save(client, "Big ones", object_type="Transaction", conditions=[
            {"field": "amount", "operator": "range", "value": {"min": 100}},
        ])

        view = client.get("/api/saved-views").json()["views"][0]

        assert view["conditions"][0]["field"] == "amount"
        assert view["disabled_conditions"] == []

    def test_a_condition_the_caller_cannot_run_is_disabled_and_named(
            self, client):
        """WIRED-1, and the case the old round-trip test was hitting
        by accident -- it filtered a Customer view on `amount`, a
        Transaction field, and the route returned it verbatim so a
        condition that could never run came back looking live.

        DISABLED AND NAMED, not dropped silently. The method's own
        reasoning: dropping silently is the worst option, because "the
        user sees more rows than the search promised and concludes
        their data changed".
        """
        _as(client, "bob")
        _save(client, "Mixed", object_type="Customer", conditions=[
            {"field": "region", "operator": "equals", "value": "us-west"},
            {"field": "amount", "operator": "range", "value": {"min": 100}},
        ])

        view = client.get("/api/saved-views").json()["views"][0]

        # The runnable one survives, keyed by its own field name.
        assert [c["field"] for c in view["conditions"]] == ["region"]
        # The impossible one is NAMED rather than vanishing.
        assert view["disabled_conditions"] == ["amount"]

    def test_saving_the_same_name_replaces(self, client):
        """BY NAME, NOT BY ID, because that is how a person thinks
        about it: saving "High value" twice means updating it."""
        _as(client, "alice")
        _save(client, "Mine")
        _save(client, "Mine")

        assert len(client.get("/api/saved-views").json()["views"]) == 1

    def test_an_unknown_object_type_is_refused(self, client):
        """A VIEW NAMING A TYPE THE CALLER CANNOT DISCOVER would match
        nothing forever, and the refusal says so at the moment they
        can fix it."""
        _as(client, "alice")

        assert _save(client, "Nonsense", object_type="NoSuchType").status_code == 404


class TestOneCallersViewsAreNotAnothers:
    def test_listing_shows_only_your_own(self, client):
        _as(client, "bob")
        _save(client, "Bob's view")
        _as(client, "alice")

        assert client.get("/api/saved-views").json()["views"] == []

    def test_deleting_somebody_elses_is_a_404(self, client):
        _as(client, "bob")
        _save(client, "Bob's view")
        bobs = client.get("/api/saved-views").json()["views"][0]["view_id"]
        _as(client, "alice")

        response = client.delete(
            f"/api/saved-views/{bobs}", headers=_csrf_headers(client),
        )

        assert response.status_code == 404

    def test_and_it_survives(self, client):
        _as(client, "bob")
        _save(client, "Bob's view")
        bobs = client.get("/api/saved-views").json()["views"][0]["view_id"]
        _as(client, "alice")
        client.delete(f"/api/saved-views/{bobs}", headers=_csrf_headers(client))
        _as(client, "bob2")

        # Bob's own listing is the check; a fresh login as bob would
        # be cleaner but the fixture creates users once.
        _login(client, "bob", "correct-pw")
        assert len(client.get("/api/saved-views").json()["views"]) == 1


class TestDeletingYourOwn:
    def test_it_works(self, client):
        _as(client, "alice")
        _save(client, "Mine")
        mine = client.get("/api/saved-views").json()["views"][0]["view_id"]

        response = client.delete(
            f"/api/saved-views/{mine}", headers=_csrf_headers(client),
        )

        assert response.status_code == 200
        assert client.get("/api/saved-views").json()["views"] == []


class TestAnonymousCallers:
    def test_cannot_list(self, client):
        assert client.get("/api/saved-views").status_code in (401, 403)


class TestHowYouGotHere:
    """The traversal chain, which a save used to drop.

    DEV_UI.md 11.2 names it the third part of what a set IS: "a set
    needs a REPRESENTATION (object type + conditions + the traversal
    chain that produced it)". Object type and conditions were already
    stored; this was not, so "Ada Okafor's transactions" saved and
    reopened came back as transactions filtered by customer_id -- the
    same ROWS, and a different thing to read.
    """

    TRAIL = {"type": "Customer", "id": "cust_001", "field": "customer_id"}

    def test_the_trail_survives_the_round_trip(self, client):
        _as(client, "alice")
        _save(client, "Ada's transactions", object_type="Transaction",
              origin=self.TRAIL)

        views = client.get("/api/saved-views").json()["views"]

        assert views[0]["origin"] == self.TRAIL

    def test_a_search_nobody_arrived_at_by_a_link_has_none(self, client):
        """Most searches are typed. An empty object rather than null,
        so a caller never has to tell "no trail" from "old view"."""
        _as(client, "alice")
        _save(client, "All customers")

        views = client.get("/api/saved-views").json()["views"]

        assert views[0]["origin"] == {}

    def test_it_is_still_only_yours(self, client):
        """The trail names an object id, which is the same reason this
        whole store is private to its owner."""
        _as(client, "alice")
        _save(client, "Ada's transactions", object_type="Transaction",
              origin=self.TRAIL)

        _as(client, "bob")
        views = client.get("/api/saved-views").json()["views"]

        assert views == []

    def test_a_view_saved_before_the_column_existed_still_comes_back(self, client):
        """THE BUG THIS TABLE ALREADY SHIPPED ONCE, with `presentation`:
        a column added to the schema alone meant a database created
        earlier returned NO VIEWS AT ALL. The migration is the fix, and
        this is the test that it ran."""
        import sqlite3

        _as(client, "alice")
        _save(client, "Older")
        store = client.app.state.runtime_paths.data_dir / "saved_views.db"
        conn = sqlite3.connect(store)
        # The column cannot be dropped in older SQLite, so the row is
        # rewritten with the value a pre-migration row would carry.
        conn.execute("UPDATE saved_views SET origin = ''")
        conn.commit()
        conn.close()

        views = client.get("/api/saved-views").json()["views"]

        assert [v["name"] for v in views] == ["Older"]
        assert views[0]["origin"] == {}


class TestAFilterThatWillNotParse:
    """The branch that answered a broken filter with silence.

    `disabled_conditions` exists because dropping a filter silently is
    the worst option: "the user sees more rows than the search promised
    and concludes their data changed". The FilterError branch returned
    runnable=[] AND disabled=[], so a view whose conditions could not
    be parsed came back matching EVERY object of its type with nothing
    on screen saying so.

    NOT HYPOTHETICAL. The save path stored the URL's ChartFilter shape
    -- `{field, values, mode}` -- where the API's vocabulary wants
    `{field, operator, value}`, so `parse_filters` threw on every
    saved view that had a filter. Fixed at its source; this covers the
    branch, which an operator removed in a later version would reach
    again.
    """

    BROKEN = [{"field": "customer_id", "values": ["cust_001"], "mode": "keep"}]

    def test_nothing_runnable_comes_back(self, client):
        _as(client, "alice")
        _save(client, "Broken", object_type="Transaction", conditions=self.BROKEN)

        view = client.get("/api/saved-views").json()["views"][0]

        assert view["conditions"] == []

    def test_AND_THE_FIELD_IS_NAMED(self, client):
        """The half that was missing. Without it the view is a search
        that quietly matches everything."""
        _as(client, "alice")
        _save(client, "Broken", object_type="Transaction", conditions=self.BROKEN)

        view = client.get("/api/saved-views").json()["views"][0]

        assert view["disabled_conditions"] == ["customer_id"]

    def test_every_field_is_named_not_just_the_first(self, client):
        _as(client, "alice")
        _save(client, "Broken", object_type="Transaction", conditions=[
            {"field": "customer_id", "values": ["c1"], "mode": "keep"},
            {"field": "category", "values": ["refund"], "mode": "keep"},
        ])

        view = client.get("/api/saved-views").json()["views"][0]

        assert view["disabled_conditions"] == ["category", "customer_id"]

    def test_a_condition_with_no_field_at_all_names_nothing(self, client):
        """Best effort, not invention. There is no name to report."""
        _as(client, "alice")
        _save(client, "Broken", object_type="Transaction",
              conditions=[{"nonsense": True}])

        view = client.get("/api/saved-views").json()["views"][0]

        assert view["conditions"] == []
        assert view["disabled_conditions"] == []

    def test_one_broken_view_does_not_break_the_list(self, client):
        """Raising here would make a single bad saved view cost
        somebody every other view they had."""
        _as(client, "alice")
        _save(client, "Broken", object_type="Transaction", conditions=self.BROKEN)
        _save(client, "Fine", object_type="Transaction", conditions=[
            {"field": "amount", "operator": "range", "value": {"min": 100}},
        ])

        views = client.get("/api/saved-views").json()["views"]

        assert sorted(v["name"] for v in views) == ["Broken", "Fine"]
