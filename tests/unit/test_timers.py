"""The timer store (core/timers.py): persisted, keyed, at least once,
retried then dropped."""

from core.timers import MAX_ATTEMPTS, RETRY_SECONDS, TimerStore, on_set


def test_a_timer_is_due_at_its_time_and_not_before(tmp_path):
    store = TimerStore(tmp_path)
    store.set("k", "a", 100.0, {"x": 1})

    assert store.due(99.0) == []
    [timer] = store.due(100.0)
    assert (timer.kind, timer.key, timer.due_at, timer.payload) == ("k", "a", 100.0, {"x": 1})


def test_setting_again_moves_it_never_adds_a_second(tmp_path):
    store = TimerStore(tmp_path)
    store.set("k", "a", 100.0)
    store.set("k", "a", 200.0)

    assert store.due(150.0) == []
    assert [timer.due_at for timer in store.due(200.0)] == [200.0]


def test_it_survives_a_new_store_on_the_same_directory(tmp_path):
    """Persisted: a server restarted after the time fires it."""
    TimerStore(tmp_path).set("k", "a", 100.0)

    assert [timer.key for timer in TimerStore(tmp_path).due(500.0)] == ["a"]


def test_done_keeps_a_timer_moved_while_it_fired(tmp_path):
    """A handler that sets its own next time must not have it deleted
    by the bookkeeping of the run that called it."""
    store = TimerStore(tmp_path)
    store.set("k", "a", 100.0)
    [fired] = store.due(100.0)
    store.set("k", "a", 400.0)

    store.done(fired)

    assert store.get("k", "a").due_at == 400.0


def test_a_failure_is_retried_later_then_dropped(tmp_path):
    store = TimerStore(tmp_path)
    store.set("k", "a", 100.0)
    now = 100.0
    for _ in range(MAX_ATTEMPTS - 1):
        [timer] = store.due(now)
        assert store.failed(timer, now) is True
        assert store.due(now) == []
        now += RETRY_SECONDS
    [timer] = store.due(now)

    assert store.failed(timer, now) is False
    assert store.get("k", "a") is None


def test_cancel_and_next_due(tmp_path):
    store = TimerStore(tmp_path)
    assert store.next_due() is None
    store.set("k", "a", 300.0)
    store.set("k", "b", 200.0)
    assert store.next_due() == 200.0

    store.cancel("k", "b")

    assert store.next_due() == 300.0


def test_this_process_is_told_when_a_timer_is_set(tmp_path):
    """How the server's loop wakes for a timer sooner than it slept for."""
    heard = []
    remove = on_set(heard.append)
    try:
        TimerStore(tmp_path).set("k", "a", 123.0)
    finally:
        remove()
    TimerStore(tmp_path).set("k", "b", 456.0)

    assert heard == [123.0]
