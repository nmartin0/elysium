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
        _save(client, "Big ones", conditions=[
            {"field": "amount", "operator": "range", "value": {"min": 100}},
        ])

        view = client.get("/api/saved-views").json()["views"][0]

        assert view["conditions"][0]["field"] == "amount"

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
