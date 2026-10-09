"""
GET /objects/{type}/{id}/provenance.

DEV_UI.md section 5 item 5 asks for "A PROVENANCE PANEL: which source,
which bronze snapshot, which publication, when", and notes that "the
lineage for this now exists". It did -- core/mirror/lineage.py has
written `_silo`, `_source_table` and `_row_hash` per row, and
`elysium.bronze_snapshot_id` per table, for months -- with no reader
that could put them back together for one object.
"""


def _login(client, username, role):
    client.app.state.user_directory.create_user(username, "pw", "us-east", role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


class TestWhoMayAsk:
    """GATED ON manage:users, deliberately. `_silo` and `_source_table`
    name the customer's own systems, and /silos already treats those
    names as admin-only. Serving them to every reader here would widen
    that disclosure through a side door."""

    def test_an_ordinary_reader_is_refused(self, client):
        _login(client, "clerk", "editor")

        response = client.get("/api/objects/Customer/cust_001/provenance")

        assert response.status_code == 403, response.text

    def test_an_administrator_is_answered(self, client):
        _login(client, "root", "admin")

        response = client.get("/api/objects/Customer/cust_001/provenance")

        assert response.status_code == 200, response.text

    def test_it_refuses_before_it_looks(self, client):
        """The refusal must not depend on whether the object exists, or
        the status code becomes an existence oracle for somebody who
        may not ask at all."""
        _login(client, "clerk2", "editor")

        real = client.get("/api/objects/Customer/cust_001/provenance")
        unreal = client.get("/api/objects/Customer/no_such_id/provenance")

        assert real.status_code == unreal.status_code == 403


class TestWhatItAnswers:
    def test_an_unknown_object_is_an_empty_answer(self, client):
        """NOT A 404. "No such object" and "an object outside your
        compartment" must look the same."""
        _login(client, "root2", "admin")

        response = client.get("/api/objects/Customer/no_such_id/provenance")

        assert response.status_code == 200
        assert response.json() is None

    def test_an_unknown_type_is_an_empty_answer_too(self, client):
        _login(client, "root3", "admin")

        response = client.get("/api/objects/Nonexistent/x/provenance")

        assert response.status_code == 200
        assert response.json() is None

    def test_it_never_returns_the_object_s_own_values(self, client):
        """Provenance is about WHERE a row came from. A route that also
        handed back the row would be a second read path for object data,
        outside the mediator that filters it."""
        _login(client, "root4", "admin")

        body = client.get("/api/objects/Customer/cust_001/provenance").json()

        if body is not None:
            assert set(body) <= {
                "silo", "source_table", "row_hash", "bronze_snapshot_id",
            }
