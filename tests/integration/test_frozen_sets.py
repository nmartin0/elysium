"""
Frozen sets: membership fixed at an instant (formerly BLOCKING 17, saved selections, DEV_UI 11.3).

FOUNDRY'S STATIC OBJECT SET IS THE PRECEDENT: "saved as a list of
primary keys", staying "the same regardless of any changes to the
input data" -- as against a dynamic set, "a representation of the
filters". So a frozen set here is keys, and opening one is an ordinary
search narrowed to them, with the reader's own authority.

THE FIXTURE: cust_001 and cust_002 are us-west, cust_003 us-east,
cust_004 eu. Every user below is us-west unless it says otherwise.
"""

from core.frozen_sets import FrozenSetStore


def _login(client, username, region="us-west", role="customer_service"):
    client.app.state.user_directory.create_user(username, "pw", region, role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _freeze(client, **body):
    return client.post("/api/frozen-sets", json={"object_type": "Customer", **body},
                       headers=_csrf(client))


def _search(client, set_id, **params):
    return client.get("/api/objects/Customer/search",
                      params={"q": "", "frozen_set": set_id, **params})


def _ids(response):
    return sorted(str(row["id"]) for row in response.json()["results"])


class TestFreezing:
    def test_freezing_a_filter_keeps_exactly_what_matched(self, client):
        _login(client, "alice")

        frozen = _freeze(client, name="West", conditions=[
            {"field": "region", "operator": "equals", "value": "us-west"}]).json()

        assert frozen["size"] == 2
        assert _ids(_search(client, frozen["set_id"])) == ["cust_001", "cust_002"]

    def test_it_remembers_the_criteria_so_it_can_be_handed_back(self, client):
        """DEV_UI 11.3: "conversion both ways" -- a set frozen from
        criteria can be returned to them."""
        _login(client, "alice2")
        conditions = [{"field": "region", "operator": "equals", "value": "us-west"}]

        frozen = _freeze(client, name="West", conditions=conditions).json()

        assert frozen["origin"] == {"q": "", "conditions": conditions}

    def test_a_hand_picked_selection_has_no_criteria(self, client):
        _login(client, "alice3")

        frozen = _freeze(client, name="Picked", ids=["cust_002", "cust_001"]).json()

        assert frozen["origin"] == {}
        assert frozen["size"] == 2

    def test_it_records_the_publication_it_was_taken_from(self, client):
        """"frozen 14:22 -- publication 7", DEV_UI 11.4. Metadata, not a
        dependency: membership never needs it."""
        _login(client, "alice4")

        frozen = _freeze(client, name="West", ids=["cust_001"]).json()

        assert frozen["published_at"]
        assert frozen["publication_retained"] is True


class TestWhatCannotBeFrozen:
    def test_an_id_the_owner_cannot_see_is_not_frozen(self, client):
        """OTHERWISE THE SET IS AN EXISTENCE ORACLE. Freeze an id from
        another compartment, read back `not_shown`, and learn whether
        it exists. Hand-picked ids go through the mediator too."""
        _login(client, "alice5")

        frozen = _freeze(client, name="Reach", ids=["cust_001", "cust_003"]).json()

        assert frozen["size"] == 1

    def test_nothing_visible_is_refused_rather_than_saved_empty(self, client):
        """An empty set would expand to an `in` with no values, which
        the filter vocabulary refuses for good reason."""
        _login(client, "alice6")

        response = _freeze(client, name="Nothing", ids=["cust_003"])

        assert response.status_code == 400

    def test_a_set_needs_a_name(self, client):
        _login(client, "alice7")

        assert _freeze(client, name="  ", ids=["cust_001"]).status_code == 400

    def test_ids_and_a_filter_together_are_refused(self, client):
        _login(client, "alice8")

        response = _freeze(client, name="Both", ids=["cust_001"], conditions=[
            {"field": "region", "operator": "equals", "value": "us-west"}])

        assert response.status_code == 400


class TestWhoseItIs:
    def test_somebody_elses_set_is_no_set_at_all(self, client):
        """404, the same answer as an id that never existed -- a 403
        would confirm the set exists and is not yours."""
        _login(client, "owner")
        set_id = _freeze(client, name="Mine", ids=["cust_001"]).json()["set_id"]

        _login(client, "intruder")

        assert _search(client, set_id).status_code == 404
        assert client.get(f"/api/frozen-sets/{set_id}").status_code == 404
        assert _search(client, "no-such-set").status_code == 404

    def test_the_list_holds_only_ones_own(self, client):
        _login(client, "owner2")
        _freeze(client, name="Mine", ids=["cust_001"])
        _login(client, "someone_else")

        assert client.get("/api/frozen-sets").json() == []

    def test_a_set_of_one_type_does_not_apply_to_another(self, client):
        """Ids are only unique within a type. Applying a Customer set to
        Transactions would match whatever ids happen to collide."""
        _login(client, "owner3")
        set_id = _freeze(client, name="Mine", ids=["cust_001"]).json()["set_id"]

        response = client.get("/api/objects/Transaction/search",
                              params={"q": "", "frozen_set": set_id})

        assert response.status_code == 404


class TestFreezingInsideAFrozenSet:
    def test_everything_matching_means_matching_WITHIN_it(self, client):
        """Seen in the browser's own logic: the panel froze its filter
        over the whole type, so a set frozen inside a set of one came
        out holding two."""
        _login(client, "nest1")
        one = _freeze(client, name="One", ids=["cust_001"]).json()["set_id"]

        nested = _freeze(client, name="Nested", frozen_set=one, conditions=[
            {"field": "region", "operator": "equals", "value": "us-west"}]).json()

        assert nested["size"] == 1
        assert nested["origin"] == {"within": one}


class TestOpeningIt:
    def test_filtering_WITHIN_a_frozen_set_narrows_it(self, client):
        """The ordinary case, not an error: the set's condition is
        ANDed with whatever else is asked."""
        _login(client, "bob")
        set_id = _freeze(client, name="Two", ids=["cust_001", "cust_002"]).json()["set_id"]

        narrowed = _search(client, set_id, conditions='[{"field": "name", '
                           '"operator": "equals", "value": "Ada Okafor"}]')

        assert _ids(narrowed) == ["cust_001"]

    def test_every_route_that_takes_a_set_takes_a_frozen_one(self, client):
        """Count, aggregate, matching-ids and export already work on
        conditions, so they work on a frozen set without a second read
        path."""
        _login(client, "bob2")
        set_id = _freeze(client, name="One", ids=["cust_001"]).json()["set_id"]

        count = client.post("/api/objects/Customer/count",
                            json={"criteria": {}, "frozen_set": set_id},
                            headers=_csrf(client)).json()
        matching = client.get("/api/objects/Customer/matching-ids",
                              params={"frozen_set": set_id}).json()
        export = client.post("/api/objects/Customer/export",
                             json={"criteria": {}, "frozen_set": set_id},
                             headers=_csrf(client))

        assert count["count"] == 1
        assert matching["object_ids"] == ["cust_001"]
        assert "cust_001" in export.text and "cust_002" not in export.text

    def test_and_WITHOUT_one_they_are_unchanged(self, client):
        """THE CONTROL. Narrowing that leaked into ordinary requests
        would pass every test above."""
        _login(client, "bob3")
        _freeze(client, name="One", ids=["cust_001"])

        count = client.post("/api/objects/Customer/count", json={"criteria": {}},
                            headers=_csrf(client)).json()

        assert count["count"] == 2


class TestAMemberThatCannotBeShown:
    def test_it_is_counted_not_hidden(self, client):
        """A deleted member and one outside the reader's compartment
        look the same -- "1 of 2 not shown" -- so the set never silently
        looks smaller than it is, and never says which reason applies.

        WRITTEN THROUGH THE STORE because the route, correctly, will not
        freeze an id its owner cannot see; this is the state a set
        reaches when an object is deleted after freezing."""
        _login(client, "carol")
        store = FrozenSetStore(client.app.state.runtime_paths.data_dir / "frozen_sets.db")
        set_id = store.freeze("carol", "Aged", "Customer", ["cust_001", "cust_gone"])

        detail = client.get(f"/api/frozen-sets/{set_id}").json()

        assert detail["size"] == 2
        assert detail["not_shown"] == 1
        assert _ids(_search(client, set_id)) == ["cust_001"]

    def test_and_a_member_that_left_the_compartment_reads_identically(self, client):
        """The other reason, indistinguishable from the first."""
        _login(client, "carol2")
        store = FrozenSetStore(client.app.state.runtime_paths.data_dir / "frozen_sets.db")
        set_id = store.freeze("carol2", "Aged", "Customer", ["cust_001", "cust_003"])

        detail = client.get(f"/api/frozen-sets/{set_id}").json()

        assert detail["not_shown"] == 1


class TestDeleting:
    def test_the_owner_can_and_nobody_else_can(self, client):
        _login(client, "dave")
        set_id = _freeze(client, name="Mine", ids=["cust_001"]).json()["set_id"]
        _login(client, "eve")

        assert client.delete(f"/api/frozen-sets/{set_id}",
                             headers=_csrf(client)).status_code == 404

        client.post("/api/login", json={"username": "dave", "password": "pw"})
        assert client.delete(f"/api/frozen-sets/{set_id}",
                             headers=_csrf(client)).status_code == 200
        assert client.get("/api/frozen-sets").json() == []
