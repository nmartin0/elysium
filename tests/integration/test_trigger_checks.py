"""Triggers checked when something happens (16 October),
api/trigger_checks.py and core/trigger_runs.py.

A count changes when its data changes or when a record crosses a date
window, so a trigger is checked after a change is saved, when it is
made, after a sync, and -- only if its view has a relative date -- at
its next crossing (test_trigger_windows.py). These drive the real routes with the checker run inline
(the test client starts no lifespan, so nothing runs unless installed).
"""

import fcntl
import threading

from api.trigger_checks import TriggerChecks
from core.saved_views import SavedView
from core.trigger_runs import reads_the_clock, run_triggers, watching


def _login(client, username, role="editor"):
    client.app.state.user_directory.create_user(username, "pw", "us-west", role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _csrf(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _inline(client):
    """The checker the server installs, run at once instead of in a
    thread, so a test can look at what it did."""
    client.app.state.trigger_checks = TriggerChecks(client.app, submit=lambda fn: fn())


def _view(client, name, conditions=()):
    response = client.post(
        "/api/saved-views",
        json={"name": name, "object_type": "Customer", "conditions": list(conditions)},
        headers=_csrf(client))
    assert response.status_code in (200, 201), response.text
    return next(view["view_id"] for view in client.get("/api/saved-views").json()["views"]
                if view["name"] == name)


def _trigger(client, view_id, name, **condition):
    response = client.post("/api/triggers", json={"name": name, "view_id": view_id, **condition},
                           headers=_csrf(client))
    assert response.status_code == 200, response.text
    return response.json()["trigger_id"]


def _notes(client):
    return [note["summary"] for note in client.get("/api/notifications").json()["notifications"]]


class TestWhenATriggerIsMade:
    def test_it_is_checked_at_once(self, client):
        _login(client, "alice")
        _inline(client)
        _trigger(client, _view(client, "Mine"), "Watch mine", above=5)

        assert any("now watching" in note for note in _notes(client))

    def test_only_it_is_checked(self, client):
        """A trigger made before the checker existed stays unchecked
        when another is made: the new one is the only one asked for."""
        _login(client, "alice")
        _trigger(client, _view(client, "First"), "First", above=5)
        _inline(client)
        _trigger(client, _view(client, "Second"), "Second", above=5)

        watching_notes = [note for note in _notes(client) if "now watching" in note]
        assert len(watching_notes) == 1
        assert "Second" in watching_notes[0]


class TestWhenAChangeIsSaved:
    def test_a_saved_change_fires_the_trigger_it_moved(self, client):
        """End to end: a view of customers named Grace Hopper counts
        none; renaming one, approved, crosses "above 0" without a sync."""
        _login(client, "alice")
        _inline(client)
        view_id = _view(client, "Graces", [
            {"field": "name", "operator": "equals", "value": "Grace Hopper"}])
        _trigger(client, view_id, "Graces", above=0)

        proposed = client.post(
            "/api/actions/UpdateCustomerName",
            json={"parameters": {"customer_id": "cust_001", "new_name": "Grace Hopper"}},
            headers=_csrf(client))
        write_id = proposed.json()["pending_write"]["id"]
        confirmed = client.post(f"/api/writes/{write_id}/confirm", json={"approved": True},
                                headers=_csrf(client))
        assert confirmed.json().get("status") == "written", confirmed.text

        # "now 1, above 0" -- the crossing, not the "now watching"
        # notice, which names the threshold too.
        assert any("now 1, above 0" in note for note in _notes(client)), _notes(client)

    def test_without_the_check_it_would_wait_for_a_sync(self, client):
        """The control for the test above: the same sequence with no
        checker installed tells nobody."""
        _login(client, "alice")
        view_id = _view(client, "Graces", [
            {"field": "name", "operator": "equals", "value": "Grace Hopper"}])
        _trigger(client, view_id, "Graces", above=0)
        proposed = client.post(
            "/api/actions/UpdateCustomerName",
            json={"parameters": {"customer_id": "cust_001", "new_name": "Grace Hopper"}},
            headers=_csrf(client))
        client.post(f"/api/writes/{proposed.json()['pending_write']['id']}/confirm",
                    json={"approved": True}, headers=_csrf(client))

        assert not any("now 1, above 0" in note for note in _notes(client))

    def test_only_triggers_watching_the_written_types(self):
        customers = SavedView("v1", "c", "Customer", "", [], {}, "")
        transactions = SavedView("v2", "t", "Transaction", "", [], {}, "")

        assert watching({"Customer"})(None, customers) is True
        assert watching({"Customer"})(None, transactions) is False


class TestCoalescing:
    def test_changes_during_a_check_become_one_more_check(self, monkeypatch):
        """Twenty approvals in a minute are not twenty evaluations."""
        checked = []
        queued = []
        checks = TriggerChecks(app=None, submit=queued.append)
        monkeypatch.setattr(checks, "_check", lambda types, ids, dated: checked.append(set(types)))

        checks.after_change({"Customer"})
        checks.after_change({"Transaction"})
        checks.after_change({"Customer"})
        assert len(queued) == 1  # one runner, however many asked
        queued[0]()

        assert checked == [{"Customer", "Transaction"}]

    def test_a_failed_check_does_not_stop_the_next(self, monkeypatch):
        calls = []

        def failing(types, ids, dated):
            calls.append(types)
            raise RuntimeError("a silo is down")
        checks = TriggerChecks(app=None, submit=lambda fn: fn())
        monkeypatch.setattr(checks, "_check", failing)

        checks.after_change({"Customer"})
        checks.after_change({"Customer"})

        assert len(calls) == 2


class TestWhichReadTheClock:
    def test_only_date_filtered_views_read_the_clock(self):
        dated = SavedView("v1", "recent", "Customer", "", [
            {"field": "created", "operator": "relative_date", "value": {"since_days_ago": 30}}], {}, "")
        plain = SavedView("v2", "all", "Customer", "", [
            {"field": "name", "operator": "equals", "value": "x"}], {}, "")

        assert reads_the_clock(None, dated) is True
        assert reads_the_clock(None, plain) is False


class TestOneAtATime:
    def test_a_second_evaluation_waits_for_the_first(self, client):
        """A sync, a saved change and the clock can each start one, in
        different processes; two counting one trigger at once would both
        say "crossed"."""
        state = client.app.state
        data_dir = state.runtime_paths.data_dir
        generation = state.generation
        done = threading.Event()

        def evaluate():
            run_triggers(generation.config, data_dir, generation.mediator,
                         lambda: (generation.mediator, generation.write_mediator,
                                  state.pending_writes))
            done.set()

        with open(data_dir / "trigger_runs.lock", "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            threading.Thread(target=evaluate, daemon=True).start()
            assert not done.wait(0.5)
        assert done.wait(10)
