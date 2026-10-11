"""
Comparing two sets, and keeping one part of the comparison.

FOUNDRY'S OBJECT SET SERVICE is the precedent: two sets combine by
union, intersect and subtract, and each result is a new set. Compare
reports the three regions at once; combine keeps one as a frozen set.

THE FIXTURE: cust_001 and cust_002 are us-west, cust_003 us-east,
cust_004 eu. Every user below is us-west, so sees two customers.
"""


def _login(client, username, region="us-west", role="customer_service"):
    client.app.state.user_directory.create_user(username, "pw", region, role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _freeze(client, name, ids):
    response = client.post("/api/frozen-sets", headers=_csrf(client),
                           json={"object_type": "Customer", "name": name, "ids": ids})
    assert response.status_code == 201, response.text
    return response.json()["set_id"]


def _compare(client, left, right, object_type="Customer"):
    return client.post("/api/sets/compare", headers=_csrf(client),
                       json={"object_type": object_type, "left": left, "right": right})


def _combine(client, left, right, region, name="Kept"):
    return client.post("/api/sets/combine", headers=_csrf(client),
                       json={"object_type": "Customer", "left": left, "right": right,
                             "region": region, "name": name})


def _members(client, set_id):
    response = client.get("/api/objects/Customer/search",
                          params={"q": "", "frozen_set": set_id})
    return sorted(str(row["id"]) for row in response.json()["results"])


ONE = {"conditions": [{"field": "customer_id", "operator": "equals", "value": "cust_001"}]}


class TestComparing:
    def test_it_counts_the_three_regions(self, client):
        _login(client, "cmp1")
        both = _freeze(client, "Both", ["cust_001", "cust_002"])
        two = _freeze(client, "Two", ["cust_002"])

        counts = _compare(client, {"frozen_set": both}, {"frozen_set": two}).json()

        assert counts == {"left_only": 1, "both": 1, "right_only": 0, "scan_truncated": False}

    def test_the_sides_are_not_interchangeable(self, client):
        """THE CONTROL for the test above: swapped, the regions swap."""
        _login(client, "cmp2")
        both = _freeze(client, "Both", ["cust_001", "cust_002"])
        two = _freeze(client, "Two", ["cust_002"])

        counts = _compare(client, {"frozen_set": two}, {"frozen_set": both}).json()

        assert (counts["left_only"], counts["right_only"]) == (0, 1)

    def test_criteria_and_an_empty_side_are_sets_too(self, client):
        """An empty reference is every object of the type the caller can
        see -- the same rule every set route has."""
        _login(client, "cmp3")

        counts = _compare(client, ONE, {}).json()

        assert (counts["left_only"], counts["both"], counts["right_only"]) == (0, 1, 1)

    def test_criteria_WITHIN_a_frozen_set_narrow_it(self, client):
        """The set on screen can be a frozen set with a filter on top,
        and that is one set, as it is to every other route."""
        _login(client, "cmp3b")
        both = _freeze(client, "Both", ["cust_001", "cust_002"])

        counts = _compare(client, {"frozen_set": both, **ONE}, {}).json()

        assert (counts["left_only"], counts["both"], counts["right_only"]) == (0, 1, 1)

    def test_a_saved_view_is_run_as_its_owner_saved_it(self, client):
        _login(client, "cmp4")
        view_id = client.post("/api/saved-views", headers=_csrf(client), json={
            "name": "Just one", "object_type": "Customer",
            "conditions": ONE["conditions"]}).json()["view_id"]

        counts = _compare(client, {"saved_view": view_id}, {}).json()

        assert (counts["left_only"], counts["both"], counts["right_only"]) == (0, 1, 1)

    def test_it_never_counts_what_the_caller_cannot_see(self, client):
        """cust_003 is us-east. Named as criteria it matches nothing for
        a us-west caller, so it lands in no region."""
        _login(client, "cmp5")
        east = {"conditions": [{"field": "customer_id", "operator": "equals",
                                "value": "cust_003"}]}

        counts = _compare(client, east, {}).json()

        assert (counts["left_only"], counts["both"], counts["right_only"]) == (0, 0, 2)


class TestWhatCannotBeCompared:
    def test_a_saved_view_with_more_filters_is_refused(self, client):
        """It would be a different set from the one its owner saved."""
        _login(client, "cmp6")
        view_id = client.post("/api/saved-views", headers=_csrf(client), json={
            "name": "All", "object_type": "Customer"}).json()["view_id"]

        response = _compare(client, {"saved_view": view_id, **ONE}, {})

        assert response.status_code == 400

    def test_somebody_elses_saved_view_is_no_view(self, client):
        _login(client, "cmp7")
        view_id = client.post("/api/saved-views", headers=_csrf(client), json={
            "name": "Mine", "object_type": "Customer"}).json()["view_id"]
        _login(client, "cmp7_other")

        assert _compare(client, {"saved_view": view_id}, {}).status_code == 404

    def test_somebody_elses_frozen_set_is_no_set(self, client):
        _login(client, "cmp8")
        set_id = _freeze(client, "Mine", ["cust_001"])
        _login(client, "cmp8_other")

        assert _compare(client, {"frozen_set": set_id}, {}).status_code == 404

    def test_a_set_of_another_type_is_no_set(self, client):
        _login(client, "cmp9")
        set_id = _freeze(client, "Mine", ["cust_001"])

        assert _compare(client, {"frozen_set": set_id}, {},
                        object_type="Transaction").status_code == 404

    def test_a_bad_condition_is_a_400_not_a_500(self, client):
        _login(client, "cmp10")

        response = _compare(client, {"conditions": [{"field": "region"}]}, {})

        assert response.status_code == 400


class TestKeepingAPart:
    def test_each_region_keeps_exactly_its_members(self, client):
        _login(client, "keep1")
        both = {"frozen_set": _freeze(client, "Both", ["cust_001", "cust_002"])}
        two = {"frozen_set": _freeze(client, "Two", ["cust_002"])}

        kept = {region: _combine(client, both, two, region, name=region).json()["set_id"]
                for region in ("left_only", "both", "either")}

        assert _members(client, kept["left_only"]) == ["cust_001"]
        assert _members(client, kept["both"]) == ["cust_002"]
        assert _members(client, kept["either"]) == ["cust_001", "cust_002"]

    def test_both_means_both_when_each_side_has_its_own(self, client):
        """SEEN IN THE BROWSER: the comparison said 40 in both and the
        kept set held 202 -- every member of the right-hand side. The
        test above could not see it, because its right side was inside
        its left. Here each side has a member the other lacks."""
        _login(client, "keep1b")
        one = {"frozen_set": _freeze(client, "One", ["cust_001"])}

        kept = _combine(client, one, {}, "both").json()

        assert _members(client, kept["set_id"]) == ["cust_001"]

    def test_every_kept_part_is_the_size_the_comparison_said(self, client):
        """THE INVARIANT the bug above broke: what is kept is what was
        counted. Asymmetric sides, so no region is a trivial copy."""
        _login(client, "keep1c")
        one = {"frozen_set": _freeze(client, "One", ["cust_001"])}
        everyone = {}
        counts = _compare(client, one, everyone).json()
        counts["either"] = counts["left_only"] + counts["both"] + counts["right_only"]

        for region in ("both", "right_only", "either"):
            kept = _combine(client, one, everyone, region, name=region).json()
            assert kept["size"] == counts[region], region

    def test_the_right_hand_part_is_the_right_hand_part(self, client):
        _login(client, "keep2")

        kept = _combine(client, ONE, {}, "right_only").json()

        assert _members(client, kept["set_id"]) == ["cust_002"]

    def test_it_records_what_it_was_made_from(self, client):
        """So the notice can say "made by comparing" rather than offering
        a return to criteria it never had."""
        _login(client, "keep3")

        kept = _combine(client, ONE, {}, "right_only").json()

        assert kept["origin"] == {"compare": {"left": ONE, "right": {}, "region": "right_only"}}

    def test_an_empty_part_is_refused_not_saved(self, client):
        _login(client, "keep4")

        assert _combine(client, ONE, {}, "left_only").status_code == 400

    def test_an_unknown_region_is_refused(self, client):
        _login(client, "keep5")

        assert _combine(client, ONE, {}, "neither").status_code == 400
