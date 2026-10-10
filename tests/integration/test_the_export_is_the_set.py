"""The set on screen, as a file somebody opens in a spreadsheet.

DEV_UI.md section 5 item 1 lists "exported" among what makes a set a
real thing, and section 3 records what the prior art's object explorer
does: "search, filter, work with the resulting set, and export it.
Needs no pre-configuration."

WHAT MAKES THIS DIFFERENT FROM READING THE SAME ROWS ON SCREEN is that
the result is a FILE, and a file is opened later, by somebody else, on
a machine nobody governs. So: no column the caller may not read, no
cell that can execute, no silent truncation, and the same MAC as every
other read.
"""

import csv
import io

from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


def _as(client, username, role="customer_service"):
    client.app.state.user_directory.create_user(
        username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _export(client, object_type="Customer", **body):
    return client.post(
        f"/api/objects/{object_type}/export",
        json=body,
        headers=_csrf_headers(client),
    )


def _rows(response) -> list[list[str]]:
    return list(csv.reader(io.StringIO(response.text)))


class TestItIsAFile:
    def test_it_comes_back_as_csv(self, client):
        _as(client, "alice")

        response = _export(client)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")

    def test_the_browser_is_told_to_save_it(self, client):
        _as(client, "alice")

        response = _export(client)

        assert "attachment" in response.headers["content-disposition"]

    def test_the_name_says_which_type_and_when(self, client):
        """A live set's membership is only true as of when it was
        taken, and somebody exporting twice in a morning has to be
        able to tell the two apart."""
        _as(client, "alice")

        disposition = _export(client).headers["content-disposition"]

        assert "Customer-" in disposition and disposition.endswith('.csv"')

    def test_it_is_not_cached(self, client):
        """A set is a live thing, and a cached copy of one is a lie
        with a timestamp on it."""
        _as(client, "alice")

        assert _export(client).headers["cache-control"] == "no-store"


class TestItIsTheSet:
    def test_a_header_and_a_row_per_object(self, client):
        _as(client, "alice")

        rows = _rows(_export(client))

        assert len(rows) > 1
        assert rows[0]

    def test_the_id_comes_first(self, client):
        """A row without one cannot be matched back to anything, and it
        is what somebody pastes into a filter to come back to one."""
        _as(client, "alice")

        assert _rows(_export(client))[0][0] == "customer_id"

    def test_a_filter_narrows_the_file(self, client):
        """NOT ON `region`, which a first version used: alice's own MAC
        already scopes her to us-west, so filtering on it narrowed
        nothing and the test compared a number with itself."""
        _as(client, "alice")

        everything = _rows(_export(client))
        assert len(everything) > 2, "the fixture must have rows to narrow"
        one_name = everything[1][everything[0].index("name")]

        narrowed = _rows(_export(client, conditions=[
            {"field": "name", "operator": "in", "value": [one_name]},
        ]))

        assert len(narrowed) == 2, "a header and the one row"
        assert len(narrowed) < len(everything)

    def test_a_filter_matching_nothing_gives_a_header_and_no_rows(self, client):
        """Not an empty file. Somebody who exports a set that matches
        nothing should get a file saying which columns matched
        nothing, rather than one they cannot open."""
        _as(client, "alice")

        rows = _rows(_export(client, conditions=[
            {"field": "region", "operator": "in", "value": ["nowhere"]},
        ]))

        assert len(rows) == 1 and rows[0][0] == "customer_id"


class TestWhatTheCallerMayNotRead:
    def test_a_field_they_cannot_read_is_NOT_A_COLUMN(self, client):
        """DEV_UI.md 9.7 wants "'Not permitted', 'restricted' and a
        real NULL" to look like three different things, and a CSV has
        exactly ONE empty cell for all three. Dropping the column is
        the only honest option left: a reader can see a column is
        absent, where a column of blanks reads as "nobody has an email
        address"."""
        # A ROLE THAT CAN DISCOVER `email` AND NOT READ IT -- the
        # middle rung. A first version used `customer_service_no_email`,
        # which cannot discover it either, so `email` was never a
        # candidate column and deleting the route's `readable` check
        # left this test green. Found by a control.
        _as(client, "nosy", role="customer_service_sees_email_exists")

        header = _rows(_export(client))[0]

        assert "email" not in header
        assert "name" in header, "and the ones they CAN read are still there"

    def test_the_withheld_field_IS_in_their_schema(self, client):
        """The guard above is only meaningful while this is true: the
        caller may know `email` exists. If a later change made it
        invisible, the export would drop it for the wrong reason and
        the test would still pass."""
        _as(client, "nosy", role="customer_service_sees_email_exists")

        schema = client.get("/api/me/visible-schema").json()
        fields = schema["Customer"]["fields"]

        assert "email" in fields
        assert fields["email"]["readable"] is False

    def test_a_type_they_cannot_see_is_a_404(self, client):
        """The same answer as a type that does not exist. Saying "you
        may not export that" would confirm it does."""
        _as(client, "alice")

        assert _export(client, object_type="NoSuchType").status_code == 404

    def test_an_anonymous_caller_may_not(self, client):
        assert client.post("/api/objects/Customer/export", json={}).status_code in (401, 403)


class TestNoCellCanExecute:
    """`AUDIT_CHECKLIST.csv` R35: "Becomes live the moment an export is
    built, and should be built WITH the escaping rather than after".

    The unit tests beside `core/export.py` cover the escaping itself;
    this covers that the ROUTE uses it, which is the half a mutation
    could remove without touching that module.
    """

    def test_a_formula_in_real_data_arrives_defused(self, client, monkeypatch):
        _as(client, "alice")

        # A VALUE NO FIXTURE CONTAINS, injected at the one place the
        # route reads a field, so the test does not depend on the
        # deployment's own data holding an attack.
        original = type(client.app.state.generation.mediator).get_object

        def poisoned(self, user, object_type, object_id, fields, **kwargs):
            answer = original(self, user, object_type, object_id, fields, **kwargs)
            if "name" in (answer or {}):
                answer["name"] = "=cmd|' /c calc'!A1"
            return answer

        monkeypatch.setattr(
            type(client.app.state.generation.mediator), "get_object", poisoned)

        text = _export(client).text

        assert "=cmd" in text, "the value is still there"
        assert "\"'=cmd" in text, "and it cannot execute"
        assert '"=cmd' not in text


class TestItRefusesRatherThanTruncates:
    def test_too_many_is_a_refusal(self, client, monkeypatch):
        """A file that silently held the first 1000 of 1500 rows is
        worse than no file: a spreadsheet gives no sign it is short,
        and every total computed from it would be wrong in a way
        nobody could see."""
        import api.routes as routes

        _as(client, "alice")
        monkeypatch.setattr(routes, "MAX_BULK_OBJECTS", 1)

        response = _export(client)

        assert response.status_code == 400

    def test_the_refusal_names_the_real_count(self, client, monkeypatch):
        import api.routes as routes

        _as(client, "alice")
        monkeypatch.setattr(routes, "MAX_BULK_OBJECTS", 1)

        detail = _export(client).json()["detail"]

        assert "at most 1" in detail
        assert "Narrow the filter" in detail

    def test_a_set_at_the_ceiling_is_allowed(self, client, monkeypatch):
        import api.routes as routes

        _as(client, "alice")
        everything = len(_rows(_export(client))) - 1
        monkeypatch.setattr(routes, "MAX_BULK_OBJECTS", everything)

        assert _export(client).status_code == 200


class TestMacApplies:
    def test_two_people_get_different_files(self, client):
        """Two users exporting the same set get different rows, which
        is correct -- the export is a read, and reads are scoped."""
        _as(client, "westerner")
        west = len(_rows(_export(client)))

        client.app.state.user_directory.create_user(
            "easterner", "correct-pw", "us-east", "customer_service")
        _login(client, "easterner", "correct-pw")
        east = len(_rows(_export(client)))

        assert west != east
