"""
A reload in one worker reaches every worker.

WHY THIS EXISTS. With several uvicorn workers, a reload swapped the
configuration only in the process that handled it. An approved role
change reached ONE worker; the rest kept enforcing the old roles --
including a grant just withdrawn, still honoured by most of the
deployment.

NOW an explicit reload raises a shared epoch, and every worker checks it
before each request and rebuilds itself when behind.

TWO WORKERS, FOR REAL: two apps from create_app() over the SAME data
directory. They share every database -- sessions, credentials, roles --
and each holds its own configuration in memory, which is exactly what
separate worker processes do.
"""

import pytest
from fastapi.testclient import TestClient

from tests.integration.test_api import _csrf_headers, _login  # noqa: F401


@pytest.fixture
def worker_b(client):
    from api.app import create_app

    return TestClient(create_app(client.app.state.runtime_paths))


def _user(client, username, role):
    directory = client.app.state.user_directory
    if not directory.user_exists(username):
        directory.create_user(username, "correct-pw", "us-west", role)


def _approve_widening_on_a(client):
    """dana proposes, erin approves -- all on worker A."""
    _user(client, "dana", "debug")
    _user(client, "erin", "debug")
    _login(client, "dana", "correct-pw")
    grants = client.get("/api/roles").json()["roles"]["customer_service"]
    change = client.post(
        "/api/roles/changes",
        json={"role_name": "customer_service", "grants": sorted({*grants, "read:Account"})},
        headers=_csrf_headers(client),
    ).json()["change_id"]
    _login(client, "erin", "correct-pw")
    response = client.post(
        f"/api/roles/changes/{change}/approve", headers=_csrf_headers(client),
    )
    assert response.status_code == 200, response.text


def _visible_types(worker, username):
    _login(worker, username, "correct-pw")
    return set(worker.get("/api/me/visible-schema").json())


class TestAnApprovalReachesEveryWorker:
    def test_worker_b_enforces_a_role_change_approved_on_worker_a(self, client, worker_b):
        """ENFORCEMENT, NOT A LISTING. A customer_service user served by
        worker B must see what the approval on worker A granted."""
        _user(client, "cy", "customer_service")
        assert "Account" not in _visible_types(worker_b, "cy")

        _approve_widening_on_a(client)

        assert "Account" in _visible_types(worker_b, "cy")

    def test_and_worker_b_lists_the_new_roles(self, client, worker_b):
        _approve_widening_on_a(client)
        _login(worker_b, "erin", "correct-pw")

        assert "read:Account" in worker_b.get("/api/roles").json()["roles"]["customer_service"]


class TestOnlyAskedForReloadsAreFollowed:
    def test_an_edit_nobody_reloaded_is_not_picked_up(self, client, worker_b):
        """WHEN AN EDIT TAKES EFFECT stays the operator's decision. The
        epoch rises on an explicit reload, never because a file changed,
        so worker B does not rebuild on its own."""
        before = worker_b.app.state.generation

        _user(client, "cy", "customer_service")
        _login(worker_b, "cy", "correct-pw")
        worker_b.get("/api/me/visible-schema")

        assert worker_b.app.state.generation is before


class TestAFollowerDoesNotAnnounce:
    def test_following_leaves_the_epoch_where_it_was(self, client, worker_b):
        """A FOLLOWER THAT ANNOUNCED would set the others off again,
        forever. One approval, one epoch."""
        _approve_widening_on_a(client)
        after_approval = client.app.state.config_history.reload_epoch()

        _visible_types(worker_b, "erin")

        assert client.app.state.config_history.reload_epoch() == after_approval
        assert worker_b.app.state.reload_epoch == after_approval


class TestAFailedFollowIsNotRetriedEveryRequest:
    def test_it_waits_for_the_next_epoch(self, client, worker_b, monkeypatch):
        """A BROKEN CONFIGURATION WILL NOT BUILD on the second try
        either. Retrying per request would cost a failed build every
        request and change nothing -- so the failed epoch is remembered,
        and this worker keeps its working configuration until the next
        reload is announced."""
        import api.reload as reload

        _approve_widening_on_a(client)
        kept = worker_b.app.state.generation
        attempts = []

        def broken(*args, **kwargs):
            attempts.append(1)
            raise ValueError("a file on this worker's disk is broken")
        monkeypatch.setattr(reload, "build_generation", broken)

        for _ in range(3):
            _visible_types(worker_b, "erin")

        assert len(attempts) == 1
        assert worker_b.app.state.generation is kept
