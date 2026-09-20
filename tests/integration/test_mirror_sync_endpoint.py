"""
Starting a sync from the panel, without waiting for it.

A SYNC IS NOT INSTANT. Two seconds on the shipped fixtures, but
ROADMAP.md measured 500,000 rows in 2.46s and about a minute for ten
million. A synchronous request would hold a connection for that long,
and the ONE worker process with it.

SO IT RUNS ON A THREAD, the same shape as `install_sighup_handler`,
which reloads configuration that way and injects its thread factory
for exactly the reason this one does.

NOTHING NEW REPORTS THE RESULT. `run_sync()` already records every
attempt in sync_attempts.db, and the panel already polls -- so the
outcome arrives through machinery that exists.

AND NOTHING NEW GUARDS IT. `run_sync()` takes an exclusive flock and
yields False if another holds it, so a second sync cannot start.
"""

import pytest

from tests.integration.test_api import (  # noqa: F401
    _csrf_headers,
    _login,
    with_roles,
)


class _CapturedThread:
    """Holds the thread instead of starting it.

    THE SAME TRICK api/reload.py's OWN TESTS USE. A test that really
    started a sync would race the assertion and leave a thread writing
    to a mirror after the test finished.
    """

    started: list = []

    def __init__(self, target=None, daemon=None, **kwargs):
        self._target = target

    def start(self):
        _CapturedThread.started.append(self._target)


@pytest.fixture(autouse=True)
def captured(client):
    _CapturedThread.started = []
    client.app.state.sync_thread_factory = _CapturedThread
    yield _CapturedThread
    del client.app.state.sync_thread_factory


def _as_admin(client):
    """A ROLE HOLDING manage:deployment, built for this test.

    NO SHIPPED FIXTURE ROLE HAS IT -- verified, and that is the point
    of `with_roles`: a grant this powerful should not be lying around
    in a fixture where a test could pick it up by accident.
    """
    with_roles(
        client.app,
        syncer={"allowed_actions": frozenset(["manage:deployment"])},
    )
    client.app.state.user_directory.create_user(
        "root", "correct-pw", None, "syncer")
    _login(client, "root", "correct-pw")


class TestALiveDeploymentHasNoMirrorToFill:
    def test_it_refuses(self, client, captured):
        """THE INTEGRATION FIXTURE READS LIVE, declared explicitly when
        the mirror became the default -- so this is the state those
        tests run in, and the refusal is the right answer for it.

        Starting a sync here would work and serve nobody, which is
        worse than refusing.
        """
        _as_admin(client)

        response = client.post(
            "/api/admin/mirror/sync", headers=_csrf_headers(client),
        )

        assert response.status_code == 409
        assert captured.started == []


def _reading_from_mirror(client):
    """Flips this deployment onto the mirror for one test.

    THE FIXTURE DECLARES `read_from_mirror: false`, so tests needing
    the mirror path have to say so.

    BY REPLACING THE CONFIG, not by assigning to it. A
    DeploymentGeneration is FROZEN -- assigning raises
    FrozenInstanceError, which is the immutability doing its job and
    caught this attempt immediately.
    """
    import dataclasses

    generation = client.app.state.generation
    client.app.state.generation = dataclasses.replace(
        generation,
        config=dataclasses.replace(generation.config, read_from_mirror=True),
    )


class TestStartingASync:
    def test_it_returns_before_the_sync_finishes(self, client, captured):
        _as_admin(client)
        _reading_from_mirror(client)

        response = client.post("/api/admin/mirror/sync", headers=_csrf_headers(client))

        assert response.status_code == 200
        assert response.json()["started"] is True

    def test_it_actually_starts_one(self, client, captured):
        """THE CONTROL ON THE TEST ABOVE. A route returning
        {"started": true} without starting anything would pass it."""
        _as_admin(client)
        _reading_from_mirror(client)

        client.post("/api/admin/mirror/sync", headers=_csrf_headers(client))

        assert len(captured.started) == 1

    def test_it_says_where_the_outcome_will_appear(self, client, captured):
        # A BUTTON THAT RETURNS INSTANTLY looks like it did nothing.
        _as_admin(client)
        _reading_from_mirror(client)

        detail = client.post("/api/admin/mirror/sync", headers=_csrf_headers(client)).json()["detail"]

        assert "last-attempt" in detail


class TestWhoMayStartOne:
    def test_an_ordinary_user_may_not(self, client, captured):
        """A STRICTER BAR THAN READING THE PANEL, because this one DOES
        something: a sync reads a customer's database and rewrites the
        mirror every user then reads."""
        client.app.state.user_directory.create_user(
            "alice", "correct-pw", "us-west", "customer_service")
        _login(client, "alice", "correct-pw")

        assert client.post("/api/admin/mirror/sync", headers=_csrf_headers(client)).status_code == 403

    def test_and_nothing_was_started(self, client, captured):
        client.app.state.user_directory.create_user(
            "alice", "correct-pw", "us-west", "customer_service")
        _login(client, "alice", "correct-pw")

        client.post("/api/admin/mirror/sync", headers=_csrf_headers(client))

        assert captured.started == []

    def test_an_anonymous_caller_may_not(self, client, captured):
        # NO CSRF HEADER, because an anonymous caller has no session and
        # therefore no token. Asking for one raises before the request
        # is made, which would test the helper rather than the route.
        assert client.post("/api/admin/mirror/sync").status_code in (401, 403)
