"""A date-filtered trigger wakes when a record crosses its window
(core/trigger_windows.py), end to end through the real routes.

Pinned to a fixed now: the fixture's transactions are dated May to July
2026. alice (us-west) sees four -- 1 May twice, 2 June and 14 June. With
"in the last 60 days" at 20 July noon, the window opens 21 May noon, so
2 June and 14 June are inside; 2 June leaves at 2 June + 60 days, which
is 1 August midnight UTC, and 14 June at 13 August.
"""

from datetime import UTC, datetime
from pathlib import Path

import core.filters
import core.trigger_windows
from api.timer_service import fire_due
from api.trigger_checks import window_timer
from core.saved_views import SavedView
from core.timers import TimerStore
from core.trigger_windows import KIND, MIN_SPACING_SECONDS, _instant, next_crossing, schedule
from tests.integration.test_trigger_checks import _csrf, _inline, _notes

AUGUST_1 = datetime(2026, 8, 1, tzinfo=UTC)
AUGUST_13 = datetime(2026, 8, 13, tzinfo=UTC)


class _Clock:
    """One present for the filter and the scheduler, movable."""

    def __init__(self, monkeypatch, at):
        self.at = at
        real = core.filters.resolve_relative_date
        monkeypatch.setattr(core.filters, "resolve_relative_date",
                            lambda value, now=None: real(value, now or self.at))
        monkeypatch.setattr(core.trigger_windows, "now", lambda: self.at)


def _recent_transactions_trigger(client, **condition):
    client.app.state.user_directory.create_user("alice", "pw", "us-west", "customer_service")
    client.post("/api/login", json={"username": "alice", "password": "pw"})
    _inline(client)
    client.post("/api/saved-views", json={
        "name": "Recent", "object_type": "Transaction",
        "conditions": [{"field": "transaction_date", "operator": "relative_date",
                        "value": {"since_days_ago": 60}}],
    }, headers=_csrf(client))
    view_id = client.get("/api/saved-views").json()["views"][0]["view_id"]
    response = client.post("/api/triggers", json={"name": "Recent", "view_id": view_id, **condition},
                           headers=_csrf(client))
    assert response.status_code == 200, response.text
    return response.json()["trigger_id"]


def _timers(client):
    return TimerStore(Path(client.app.state.runtime_paths.data_dir))


class TestItSetsATimerForTheNextCrossing:
    def test_made_now_it_wakes_when_the_first_record_leaves(self, client, monkeypatch):
        _Clock(monkeypatch, datetime(2026, 7, 20, 12, tzinfo=UTC))
        trigger_id = _recent_transactions_trigger(client, fell=1)

        assert _timers(client).get(KIND, trigger_id).due_at == AUGUST_1.timestamp()

    def test_the_timer_firing_tells_them_and_sets_the_next(self, client, monkeypatch):
        clock = _Clock(monkeypatch, datetime(2026, 7, 20, 12, tzinfo=UTC))
        trigger_id = _recent_transactions_trigger(client, fell=1)
        clock.at = datetime(2026, 8, 1, 0, 1, tzinfo=UTC)

        ran = fire_due(client.app, {KIND: window_timer}, clock=lambda: clock.at.timestamp())

        assert ran == 1
        assert any("(2 to 1)" in note for note in _notes(client)), _notes(client)
        assert _timers(client).get(KIND, trigger_id).due_at == AUGUST_13.timestamp()

    def test_nothing_left_to_cross_means_no_timer(self, client, monkeypatch):
        clock = _Clock(monkeypatch, datetime(2026, 7, 20, 12, tzinfo=UTC))
        trigger_id = _recent_transactions_trigger(client, fell=1)
        clock.at = datetime(2026, 9, 1, tzinfo=UTC)

        window_timer(client.app, trigger_id, {})

        assert _timers(client).get(KIND, trigger_id) is None

    def test_a_trigger_without_a_date_filter_sets_none(self, client):
        client.app.state.user_directory.create_user("alice", "pw", "us-west", "customer_service")
        client.post("/api/login", json={"username": "alice", "password": "pw"})
        _inline(client)
        client.post("/api/saved-views", json={"name": "All", "object_type": "Transaction"},
                    headers=_csrf(client))
        view_id = client.get("/api/saved-views").json()["views"][0]["view_id"]
        trigger_id = client.post("/api/triggers", json={"name": "All", "view_id": view_id, "above": 9},
                                 headers=_csrf(client)).json()["trigger_id"]

        assert _timers(client).get(KIND, trigger_id) is None


class TestTheCrossing:
    def test_never_sooner_than_a_minute(self):
        """A record crossing right now wakes the trigger a minute out,
        so a busy table cannot spin it."""
        at = datetime(2026, 8, 1, tzinfo=UTC)

        class Edge:  # the earliest record is exactly 60 days old
            def aggregate_by_field(self, *args, **kwargs):
                return {None: "2026-06-02T00:00:00+00:00"}

        class Timers:
            def set(self, kind, key, due_at, payload=None):
                self.due_at = due_at

        trigger = type("T", (), {"trigger_id": "t"})()
        view = SavedView("v", "Recent", "Transaction", "", [
            {"field": "transaction_date", "operator": "relative_date",
             "value": {"since_days_ago": 60}}], {}, "")
        timers = Timers()

        schedule(timers, trigger, Edge(), view, [object()], at)

        assert timers.due_at == at.timestamp() + MIN_SPACING_SECONDS

    def test_more_than_n_days_ago_wakes_when_a_record_enters(self, client, monkeypatch):
        """"more than 60 days ago" at 20 July holds the two 1 May
        records; 2 June enters on 1 August."""
        at = datetime(2026, 7, 20, 12, tzinfo=UTC)
        _Clock(monkeypatch, at)
        client.app.state.user_directory.create_user("alice", "pw", "us-west", "customer_service")
        client.post("/api/login", json={"username": "alice", "password": "pw"})
        mediator = client.app.state.generation.mediator
        alice = client.app.state.user_directory.get_user_record("alice")
        view = SavedView("v", "Old", "Transaction", "", [
            {"field": "transaction_date", "operator": "relative_date",
             "value": {"until_days_ago": 60}}], {}, "")

        assert next_crossing(mediator, view, [alice], at) == AUGUST_1


def test_stored_dates_and_times_are_read_as_utc():
    assert _instant("2026-06-02") == datetime(2026, 6, 2, tzinfo=UTC)
    assert _instant("2026-06-02T10:30:00Z") == datetime(2026, 6, 2, 10, 30, tzinfo=UTC)
    assert _instant("2026-06-02T10:30:00") == datetime(2026, 6, 2, 10, 30, tzinfo=UTC)
    assert _instant(datetime(2026, 6, 2).date()) == datetime(2026, 6, 2, tzinfo=UTC)
    assert _instant("not a date") is None
    assert _instant(42) is None


def test_the_server_starting_checks_every_date_filtered_trigger(client, monkeypatch):
    """Crossings while it was down, and a first timer for each -- and
    only date-filtered ones: nothing else can have moved."""
    from api.trigger_checks import TriggerChecks

    _Clock(monkeypatch, datetime(2026, 7, 20, 12, tzinfo=UTC))
    client.app.state.user_directory.create_user("alice", "pw", "us-west", "customer_service")
    client.post("/api/login", json={"username": "alice", "password": "pw"})
    for name, conditions in (("Recent", [{"field": "transaction_date", "operator": "relative_date",
                                          "value": {"since_days_ago": 60}}]),
                             ("All", [])):
        client.post("/api/saved-views", json={"name": name, "object_type": "Transaction",
                                              "conditions": conditions}, headers=_csrf(client))
    views = {view["name"]: view["view_id"] for view in client.get("/api/saved-views").json()["views"]}
    for name, view_id in views.items():
        client.post("/api/triggers", json={"name": name, "view_id": view_id, "above": 9},
                    headers=_csrf(client))

    TriggerChecks(client.app, submit=lambda fn: fn()).after_start()

    watching = [note for note in _notes(client) if "now watching" in note]
    assert len(watching) == 1 and watching[0].startswith("Recent"), watching
