"""
Triggers somebody made, rather than a deployment declared.

OWNED BY THEIR CREATOR, AND RUN AS THEM. That is what makes a
UI-created trigger safe to offer without a new grant: its effects are
attenuated by construction. Alice's trigger counts objects Alice could
already count and notifies Alice.

RECIPIENTS ARE THE OWNER, AND ONLY THE OWNER, for now. Naming another
person would be a capability its creator does not otherwise have --
sending notifications somebody did not ask for. Not a leak, since a
notification carries only its recipient's own count, but a capability,
and one worth deciding separately.

Mirror health is the counter-example and stays as it is: a BUILT-IN
notifying whoever holds `manage:deployment`, declared in code rather
than by a person.
"""

from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


def _as(client, username, role="customer_service"):
    client.app.state.user_directory.create_user(
        username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _a_view(client, name="My customers"):
    client.post(
        "/api/saved-views",
        json={"name": name, "object_type": "Customer"},
        headers=_csrf_headers(client),
    )
    return client.get("/api/saved-views").json()["views"][0]["view_id"]


def _create(client, view_id, **body):
    return client.post(
        "/api/triggers",
        json={"name": "Watch customers", "view_id": view_id, **body},
        headers=_csrf_headers(client),
    )


class TestCreatingOne:
    def test_a_trigger_comes_back(self, client):
        _as(client, "alice")
        view_id = _a_view(client)

        assert _create(client, view_id, above=5).status_code == 200
        assert len(client.get("/api/triggers").json()["triggers"]) == 1

    def test_it_starts_enabled(self, client):
        _as(client, "alice")
        _create(client, _a_view(client), above=5)

        assert client.get("/api/triggers").json()["triggers"][0]["enabled"]


class TestATriggerNeedsAQuestion:
    def test_no_threshold_is_refused(self, client):
        """A TRIGGER WITH NO CONDITION would evaluate forever and
        never fire, which reads as broken rather than as quiet."""
        _as(client, "alice")

        assert _create(client, _a_view(client)).status_code == 400

    def test_two_thresholds_are_refused(self, client):
        """ONE QUESTION PER TRIGGER. Two on one row would need an
        answer about which wins; two triggers say it plainly."""
        _as(client, "alice")

        response = _create(client, _a_view(client), above=5, gained=3)

        assert response.status_code == 400


class TestTheViewMustBeYourOwn:
    def test_somebody_elses_view_is_a_404(self, client):
        """CHECKED BY LOOKING IN THEIR LIST rather than by fetching
        and comparing. `get` takes no owner -- it is the scheduler's
        call -- so using it here would be the one place the store's
        scoping could be bypassed.
        """
        _as(client, "bob")
        bobs_view = _a_view(client, "Bob's view")
        _as(client, "alice")

        assert _create(client, bobs_view, above=5).status_code == 404

    def test_an_unknown_view_is_a_404(self, client):
        _as(client, "alice")

        assert _create(client, "no-such-view", above=5).status_code == 404


class TestOneCallersTriggersAreNotAnothers:
    def test_listing_shows_only_your_own(self, client):
        _as(client, "bob")
        _create(client, _a_view(client, "Bob's view"), above=5)
        _as(client, "alice")

        assert client.get("/api/triggers").json()["triggers"] == []

    def test_deleting_somebody_elses_is_a_404(self, client):
        _as(client, "bob")
        _create(client, _a_view(client, "Bob's view"), above=5)
        bobs = client.get("/api/triggers").json()["triggers"][0]["trigger_id"]
        _as(client, "alice")

        response = client.delete(
            f"/api/triggers/{bobs}", headers=_csrf_headers(client),
        )

        assert response.status_code == 404


class TestTurningOneOff:
    def test_it_can_be_disabled(self, client):
        """ENABLED RATHER THAN DELETED is the common case: somebody
        silencing a noisy trigger usually wants it back."""
        _as(client, "alice")
        _create(client, _a_view(client), above=5)
        trigger_id = client.get("/api/triggers").json()["triggers"][0]["trigger_id"]

        client.post(
            f"/api/triggers/{trigger_id}/enabled?enabled=false",
            headers=_csrf_headers(client),
        )

        assert not client.get("/api/triggers").json()["triggers"][0]["enabled"]

    def test_and_enabled_again(self, client):
        _as(client, "alice")
        _create(client, _a_view(client), above=5)
        trigger_id = client.get("/api/triggers").json()["triggers"][0]["trigger_id"]
        client.post(
            f"/api/triggers/{trigger_id}/enabled?enabled=false",
            headers=_csrf_headers(client),
        )

        client.post(
            f"/api/triggers/{trigger_id}/enabled?enabled=true",
            headers=_csrf_headers(client),
        )

        assert client.get("/api/triggers").json()["triggers"][0]["enabled"]


class TestAnonymousCallers:
    def test_cannot_list(self, client):
        assert client.get("/api/triggers").status_code in (401, 403)
