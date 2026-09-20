"""
Notifications, per recipient, in the product.

WHAT A NOTIFICATION IS HERE: a row somebody will see next time they
look. Not an email, not a webhook -- both are places data LEAVES the
deployment and each needs its own decision about what may cross that
line. In-product needs none, because nothing crosses.

ONE PER RECIPIENT, NEVER ONE SHARED. A notification carries only what
its recipient's own evaluation produced. There is no "notification"
object with a recipient list, and no call that returns everyone's --
so there is no privileged view for a bug to leak from.
"""


from tests.integration.test_api import (  # noqa: F401
    _csrf_headers,
    _login,
    with_roles,
)


def _store(client):
    from core.notifications import NotificationStore

    return NotificationStore(
        client.app.state.runtime_paths.data_dir / "notifications.db",
    )


def _as(client, username, role="customer_service"):
    client.app.state.user_directory.create_user(
        username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


class TestSeeingYourOwn:
    def test_an_empty_inbox_is_empty(self, client):
        _as(client, "alice")

        body = client.get("/api/notifications").json()

        assert body["notifications"] == []
        assert body["unseen"] == 0

    def test_a_notification_arrives(self, client):
        _as(client, "alice")
        _store(client).notify("alice", "mirror_health", "A sync was refused")

        body = client.get("/api/notifications").json()

        assert body["unseen"] == 1
        assert body["notifications"][0]["summary"] == "A sync was refused"


class TestNotSeeingSomebodyElses:
    def test_one_persons_notification_is_not_anothers(self, client):
        """THE PROPERTY THAT MATTERS. The store scopes by user_id IN
        THE QUERY rather than filtering afterwards, so this is not a
        check that could be forgotten -- it is the only query there
        is."""
        _store(client).notify("bob", "mirror_health", "bob's business")
        _as(client, "alice")

        assert client.get("/api/notifications").json()["notifications"] == []

    def test_marking_somebody_elses_seen_is_a_404(self, client):
        """A 404, NOT A 403. Telling a caller that a notification
        exists but is not theirs says more than refusing to say
        anything."""
        bobs = _store(client).notify("bob", "mirror_health", "bob's business")
        _as(client, "alice")

        response = client.post(
            f"/api/notifications/{bobs}/seen", headers=_csrf_headers(client),
        )

        assert response.status_code == 404

    def test_and_it_stays_unseen_for_its_owner(self, client):
        bobs = _store(client).notify("bob", "mirror_health", "bob's business")
        _as(client, "alice")
        client.post(
            f"/api/notifications/{bobs}/seen", headers=_csrf_headers(client),
        )

        assert _store(client).unseen_count("bob") == 1


class TestMarkingYourOwnSeen:
    def test_it_works(self, client):
        _as(client, "alice")
        mine = _store(client).notify("alice", "mirror_health", "mine")

        response = client.post(
            f"/api/notifications/{mine}/seen", headers=_csrf_headers(client),
        )

        assert response.status_code == 200
        assert client.get("/api/notifications").json()["unseen"] == 0


class TestAnonymousCallers:
    def test_cannot_read_notifications(self, client):
        assert client.get("/api/notifications").status_code in (401, 403)
