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
    handlers = {"ping": lambda app, key, payload: calls.append((key, payload))}

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

    fire_due(client.app, {"tick": lambda app, key, payload: store.set("tick", key, 500.0)},
             clock=lambda: 100.0)

    assert store.get("tick", "a").due_at == 500.0


def test_a_failing_handler_is_retried_not_lost(client):
    def failing(app, key, payload):
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
