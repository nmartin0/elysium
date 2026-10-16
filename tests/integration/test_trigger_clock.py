"""The server checking triggers between syncs (decided 16 October),
api/trigger_clock.py.

Driven by calling check_if_due with a clock, not by waiting for the
loop: what is under test is WHEN a check happens and that it is the
same check the sync runs, not asyncio.sleep.
"""

import dataclasses
import fcntl

import pytest

import core.trigger_runs
from api.trigger_clock import check_if_due
from tests.integration.test_triggers import _a_view, _as, _create


@pytest.fixture
def checks(monkeypatch):
    """Every check the clock runs, recorded instead of run."""
    calls = []
    monkeypatch.setattr(core.trigger_runs, "run_triggers", lambda *args: calls.append(args) or 0)
    return calls


def _every(client, minutes):
    generation = client.app.state.generation
    client.app.state.generation = dataclasses.replace(
        generation, config=dataclasses.replace(generation.config, check_triggers_every_minutes=minutes))


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

        def failing(*args):
            calls.append(args)
            raise RuntimeError("a silo is down")
        monkeypatch.setattr(core.trigger_runs, "run_triggers", failing)
        start = 5_000_000.0

        assert check_if_due(client.app, clock=lambda: start) is True
        assert check_if_due(client.app, clock=lambda: start + 60) is False
        assert len(calls) == 1


class TestWhatItChecks:
    def test_the_same_check_the_sync_runs_reaches_a_real_trigger(self, client):
        """End to end, nothing recorded instead: alice's trigger is
        evaluated as alice, and her first evaluation says it is
        watching."""
        _as(client, "alice")
        assert _create(client, _a_view(client), above=5).status_code == 200

        assert check_if_due(client.app, clock=lambda: 6_000_000.0) is True

        notes = client.get("/api/notifications").json()["notifications"]
        assert any("now watching" in note["summary"] for note in notes)
