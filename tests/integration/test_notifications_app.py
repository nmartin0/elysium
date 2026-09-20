"""
The Notifications app appears in the rail.

UNGATED, FOR THE SAME REASON AS APPROVALS. These are the caller's OWN
notifications, scoped by user in the query, so somebody with none
sees an empty page rather than a forbidden one -- the uniform denial
every read path here uses.

AND GATING WOULD BE WRONG RATHER THAN MERELY UNNECESSARY. A
notification is sent to whoever a condition names, decided per
condition; a single permission could not describe who should be able
to read theirs.
"""

from tests.integration.test_api import _login  # noqa: F401


def _as(client, username, role="customer_service"):
    client.app.state.user_directory.create_user(
        username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _app_paths(client):
    # /me/visible-apps RETURNS A BARE LIST, not an object with an
    # "apps" key -- checked rather than assumed, after a first version
    # guessed the envelope and got KeyError.
    return [app["path"] for app in client.get("/api/me/visible-apps").json()]


class TestItIsListed:
    def test_an_ordinary_user_sees_it(self, client):
        _as(client, "alice")

        assert "/notifications" in _app_paths(client)

    def test_it_has_a_name(self, client):
        _as(client, "alice")

        apps = client.get("/api/me/visible-apps").json()
        entry = [a for a in apps if a["path"] == "/notifications"][0]

        assert entry["name"] == "Notifications"


class TestItIsNotGated:
    def test_the_lowest_privileged_role_still_sees_it(self, client):
        """SOMEBODY WITH NO NOTIFICATIONS SEES AN EMPTY PAGE, not a
        forbidden one."""
        _as(client, "bob", role="customer_service_link_only")

        assert "/notifications" in _app_paths(client)
