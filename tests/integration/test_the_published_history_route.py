"""
GET /objects/{type}/{id}/published-history, exercised end to end.

THERE WAS NO SUCH TEST. The route had a unit test for its MAC filter
and nothing that called it through the app -- which is how a screen
got wired to an endpoint that returns 500 on an ordinary deployment.
The owner found it by opening an object.
"""


def _login(client, username="viewer", password="pw"):
    client.app.state.user_directory.create_user(username, password, "us-west", "editor")
    response = client.post("/api/login", json={"username": username, "password": password})
    assert response.status_code == 204, response.text


class TestItAnswersOnAnOrdinaryDeployment:
    def test_an_object_with_no_published_history_is_not_an_error(self, client):
        """THE CASE THAT BROKE. A deployment that has synced but not
        published gold has no changelog table, and asking for an
        object's source history must be an empty answer rather than a
        500 -- the panel is on every object page, so a failure here
        makes every object page fail."""
        _login(client)

        response = client.get("/api/objects/Customer/cust_001/published-history")

        assert response.status_code == 200, response.text
        assert response.json() == []

    def test_an_unknown_object_is_empty_rather_than_404(self, client):
        """Uniform denial: the response must not distinguish "no such
        object" from "not yours"."""
        _login(client)

        response = client.get("/api/objects/Customer/nope/published-history")

        assert response.status_code == 200
        assert response.json() == []

    def test_an_unknown_type_is_empty_rather_than_500(self, client):
        _login(client)

        response = client.get("/api/objects/Nonexistent/x/published-history")

        assert response.status_code == 200
        assert response.json() == []


class TestTheStateTheOwnerWasIn:
    """"Showing mirrored data, which has not been published yet" --
    synced to the mirror, gold not published. The fixture publishes as
    part of its sync, so no test had ever been in this state, which is
    exactly why the 500 reached a person before a test."""

    def test_a_mirror_without_published_gold_is_not_an_error(self, client):
        import shutil

        mirror = client.app.state.runtime_paths.data_dir / "mirror"
        for namespace in ("gold", "changelog"):
            for found in mirror.rglob(namespace):
                if found.is_dir():
                    shutil.rmtree(found)

        _login(client, "unpublished")

        response = client.get("/api/objects/Customer/cust_001/published-history")

        assert response.status_code == 200, response.text
