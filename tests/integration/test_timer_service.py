"""The loop that fires timers (api/timer_service.py).

Driven by calling fire_due with a clock rather than by waiting for the
loop: what is under test is which timers fire, once, by whom.
"""

import fcntl
from pathlib import Path

from api.timer_service import LOOK_SECONDS, MIN_SLEEP_SECONDS, fire_due, seconds_until_next
from core.timers import TimerStore


def _store(client):
    return TimerStore(Path(client.app.state.runtime_paths.data_dir))


def test_a_due_timer_runs_its_handler_once(client):
    calls = []
    _store(client).set("ping", "a", 100.0, {"n": 1})
    handlers = {"ping": lambda app, firing: calls.append((firing.key, firing.payload))}

    assert fire_due(client.app, handlers, clock=lambda: 100.0) == 1
    assert fire_due(client.app, handlers, clock=lambda: 200.0) == 0
    assert calls == [("a", {"n": 1})]


def test_one_not_yet_due_waits(client):
    calls = []
    _store(client).set("ping", "a", 100.0)

    fire_due(client.app, {"ping": lambda *args: calls.append(args)}, clock=lambda: 99.0)

    assert calls == []


def test_a_handler_setting_its_next_time_keeps_it(client):
    """How a trigger reschedules itself from inside its own timer."""
    store = _store(client)
    store.set("tick", "a", 100.0)

    fire_due(client.app, {"tick": lambda app, firing: store.set("tick", firing.key, 500.0)},
             clock=lambda: 100.0)

    assert store.get("tick", "a").due_at == 500.0


def test_a_failing_handler_is_retried_not_lost(client):
    def failing(app, firing):
        raise RuntimeError("a silo is down")
    _store(client).set("ping", "a", 100.0)

    assert fire_due(client.app, {"ping": failing}, clock=lambda: 100.0) == 0
    assert _store(client).get("ping", "a").attempts == 1


def test_a_kind_nobody_handles_is_dropped(client):
    _store(client).set("gone", "a", 100.0)

    fire_due(client.app, {}, clock=lambda: 100.0)

    assert _store(client).get("gone", "a") is None


def test_another_worker_firing_means_this_one_does_not(client):
    calls = []
    _store(client).set("ping", "a", 100.0)
    lock_path = Path(client.app.state.runtime_paths.data_dir) / "timers.lock"
    with open(lock_path, "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX)

        assert fire_due(client.app, {"ping": lambda *args: calls.append(args)},
                        clock=lambda: 100.0) == 0
    assert calls == []


def test_it_sleeps_until_the_earliest_timer_within_bounds(client):
    assert seconds_until_next(client.app, clock=lambda: 0.0) == LOOK_SECONDS
    _store(client).set("ping", "a", 30.0)
    assert seconds_until_next(client.app, clock=lambda: 0.0) == 30.0
    # Overdue -- perhaps another worker is firing it -- is a short
    # sleep, never a spin.
    assert seconds_until_next(client.app, clock=lambda: 100.0) == MIN_SLEEP_SECONDS


class TestHowLateIsTooLate:
    """Each timer's own lateness policy (core/timers.py, late_after)."""

    def _fire(self, client, now):
        seen = []
        fire_due(client.app, {"ping": lambda app, firing: seen.append(firing)}, clock=lambda: now)
        return seen

    def test_late_within_its_policy_is_on_time(self, client):
        _store(client).set("ping", "a", 1000.0, late_after=3600.0)

        [firing] = self._fire(client, 1000.0 + 3000)

        assert firing.missed is False

    def test_later_than_its_policy_is_missed_not_run_as_if_on_time(self, client):
        _store(client).set("ping", "a", 1000.0, late_after=3600.0)

        [firing] = self._fire(client, 1000.0 + 7200)

        assert firing.missed is True
        assert _store(client).get("ping", "a") is None

    def test_under_a_minute_late_is_never_a_miss(self, client):
        """Quartz's misfireThreshold: a loop that wakes on the minute
        must not call its own ordinary lateness a miss."""
        _store(client).set("ping", "a", 1000.0, late_after=1.0)

        [firing] = self._fire(client, 1000.0 + 50)

        assert firing.missed is False

    def test_no_policy_fires_however_late(self, client):
        _store(client).set("ping", "a", 1000.0)

        [firing] = self._fire(client, 1000.0 + 86400 * 30)

        assert firing.missed is False


class TestARepeatingTimer:
    HOURLY = {"every_minutes": 60}

    def test_moves_on_to_its_next_occurrence(self, client):
        _store(client).set("ping", "a", 3600.0, repeat=self.HOURLY)

        TestHowLateIsTooLate()._fire(client, 3600.0)

        assert _store(client).get("ping", "a").occurrence_at == 7200.0

    def test_catches_up_at_most_once_delivering_the_latest_still_in_time(self, client):
        """Due at 01:00, hourly, an hour's grace, found at 05:30: 05:00 is
        half an hour late -- inside the policy -- so it is delivered, ONE
        firing, counting 01:00 to 04:00 as missed. Then on to 06:00."""
        _store(client).set("ping", "a", 3600.0, late_after=3600.0, repeat=self.HOURLY)

        seen = TestHowLateIsTooLate()._fire(client, 3600.0 * 5.5)

        assert len(seen) == 1
        assert seen[0].missed is False and seen[0].at == 3600.0 * 5 and seen[0].also_missed == 4
        assert _store(client).get("ping", "a").occurrence_at == 3600.0 * 6

    def test_nothing_inside_its_policy_is_reported_missed(self, client):
        """Every six hours with an hour's grace, found three hours after
        its last occurrence: that one is missed, and so is the stored."""
        _store(client).set("ping", "a", 3600.0, late_after=3600.0, repeat={"every_minutes": 360})

        seen = TestHowLateIsTooLate()._fire(client, 3600.0 + 6 * 3600 + 3 * 3600)

        assert seen[0].missed is True and seen[0].at == 3600.0 and seen[0].also_missed == 1

    def test_a_retry_is_the_same_occurrence(self, client):
        """So its key -- what makes a second delivery a no-op -- does not
        change when a failure moves it."""
        def failing(app, firing):
            raise RuntimeError("down")
        _store(client).set("ping", "a", 3600.0, repeat=self.HOURLY)
        key_before = _store(client).get("ping", "a").occurrence_key

        fire_due(client.app, {"ping": failing}, clock=lambda: 3600.0)

        after = _store(client).get("ping", "a")
        assert after.due_at > 3600.0
        assert after.occurrence_key == key_before
