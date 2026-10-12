"""R65: the one failure a sync cannot report -- not running at all.

The sync's own health notice is written BY the sync, so a sync that
stops leaves silence identical to a healthy mirror. The dead man's
switch is now evaluated when an administrator's client asks for its
notifications: if the newest sync attempt is older than the stale
threshold, they are told, once per lapse.
"""

import sqlite3
import time

from core.mirror.sync_attempts import SyncAttempts
from tests.conftest import with_roles


def _login(client, username, role):
    client.app.state.user_directory.create_user(username, "pw", "us-west", role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _attempts(client) -> SyncAttempts:
    return SyncAttempts(client.app.state.runtime_paths.data_dir / "mirror" / "sync_attempts.db")


def _age_every_attempt(client, hours: float) -> None:
    """Moves the recorded attempts into the past, as a stopped sync would
    leave them."""
    attempts = _attempts(client)
    attempts.record("primary_sql", "customers", "synced")
    with sqlite3.connect(client.app.state.runtime_paths.data_dir / "mirror"
                         / "sync_attempts.db") as conn:
        conn.execute("UPDATE sync_attempts SET at = ?", (time.time() - hours * 3600,))


def _summaries(client) -> list[str]:
    return [n["summary"] for n in client.get("/api/notifications").json()["notifications"]]


def _operator(client, name="operator"):
    with_roles(client.app, operator={"allowed_actions": frozenset(["manage:deployment"])})
    _login(client, name, "operator")


def test_an_administrator_is_told_when_the_sync_stopped(client):
    _age_every_attempt(client, hours=30)
    _operator(client)

    assert any("No sync has run for 30 hours" in summary for summary in _summaries(client))


def test_once_per_lapse_however_often_the_client_polls(client):
    _age_every_attempt(client, hours=30)
    _operator(client, "operator2")

    for _ in range(3):
        summaries = _summaries(client)

    assert sum("No sync has run" in summary for summary in summaries) == 1


def test_a_recent_sync_says_nothing(client):
    """THE CONTROL: a mirror synced an hour ago is not overdue."""
    _age_every_attempt(client, hours=1)
    _operator(client, "operator3")

    assert not any("No sync has run" in summary for summary in _summaries(client))


def test_somebody_who_cannot_fix_it_is_not_told(client):
    """The grant that starts a sync, as the sync's own notice uses."""
    _age_every_attempt(client, hours=30)
    _login(client, "alice", "customer_service")

    assert not any("No sync has run" in summary for summary in _summaries(client))
