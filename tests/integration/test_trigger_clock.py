"""The server's clock for date-filtered triggers (revised 16 October),
api/trigger_clock.py. What it checks is in test_trigger_checks.py.

Driven by calling check_if_due with a clock, not by waiting for the
loop: what is under test is WHEN a check happens and that it is the
same check the sync runs, not asyncio.sleep.
"""

import dataclasses
import fcntl

import pytest

import core.trigger_runs
from api.trigger_clock import check_if_due
from tests.integration.test_triggers import _a_view, _as, _create, _csrf_headers


@pytest.fixture
def checks(monkeypatch):
    """Every check the clock runs, recorded instead of run."""
    calls = []
    monkeypatch.setattr(core.trigger_runs, "run_triggers", lambda *args, **kwargs: calls.append(args) or 0)
    return calls


def _every(client, minutes):
    generation = client.app.state.generation
    client.app.state.generation = dataclasses.replace(
        generation, config=dataclasses.replace(generation.config, check_date_triggers_every_minutes=minutes))


class TestWhenItChecks:
    def test_once_per_interval(self, client, checks):
        start = 1_000_000.0

        assert check_if_due(client.app, clock=lambda: start) is True
        assert check_if_due(client.app, clock=lambda: start + 14 * 60) is False
        assert check_if_due(client.app, clock=lambda: start + 15 * 60) is True
        assert len(checks) == 2

    def test_the_interval_is_the_deployments(self, client, checks):
        _every(client, 60)
        start = 2_000_000.0
        check_if_due(client.app, clock=lambda: start)

        assert check_if_due(client.app, clock=lambda: start + 30 * 60) is False
        assert check_if_due(client.app, clock=lambda: start + 60 * 60) is True

    def test_zero_turns_it_off(self, client, checks):
        _every(client, 0)

        assert check_if_due(client.app, clock=lambda: 3_000_000.0) is False
        assert checks == []

    def test_another_worker_checking_means_this_one_does_not(self, client, checks):
        """Every worker runs the loop; the file lock lets one check."""
        lock_path = client.app.state.runtime_paths.data_dir / "trigger_clock.lock"
        with open(lock_path, "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)

            assert check_if_due(client.app, clock=lambda: 4_000_000.0) is False
        assert checks == []

    def test_a_check_that_fails_is_not_retried_every_minute(self, client, monkeypatch):
        calls = []

        def failing(*args, **kwargs):
            calls.append(args)
            raise RuntimeError("a silo is down")
        monkeypatch.setattr(core.trigger_runs, "run_triggers", failing)
        start = 5_000_000.0

        assert check_if_due(client.app, clock=lambda: start) is True
        assert check_if_due(client.app, clock=lambda: start + 60) is False
        assert len(calls) == 1


class TestWhatItChecks:
    def test_the_same_check_the_sync_runs_reaches_a_date_filtered_trigger(self, client):
        """End to end, nothing recorded instead: alice's trigger on a
        view of recent transactions is evaluated as alice, and her
        first evaluation says it is watching."""
        _as(client, "alice")
        client.post("/api/saved-views", json={
            "name": "Recent", "object_type": "Transaction",
            "conditions": [{"field": "transaction_date", "operator": "relative_date",
                            "value": {"since_days_ago": 36500}}],
        }, headers=_csrf_headers(client))
        view_id = client.get("/api/saved-views").json()["views"][0]["view_id"]
        assert _create(client, view_id, above=5).status_code == 200

        assert check_if_due(client.app, clock=lambda: 6_000_000.0) is True

        notes = client.get("/api/notifications").json()["notifications"]
        assert any("now watching" in note["summary"] for note in notes)

    def test_a_trigger_without_a_date_filter_is_not_its_business(self, client):
        """Only time moves under a date filter; anything else is
        checked when data arrives, and the clock finds nothing to do."""
        _as(client, "alice")
        assert _create(client, _a_view(client), above=5).status_code == 200

        assert check_if_due(client.app, clock=lambda: 6_000_000.0) is True

        notes = client.get("/api/notifications").json()["notifications"]
        assert not any("now watching" in note["summary"] for note in notes)
