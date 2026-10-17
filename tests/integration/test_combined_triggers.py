"""Combined triggers through the real routes (17 October;
core/trigger_states.py): all or any of several conditions, held for a
while, or checked on a schedule -- each person counted with their own
authority, fired once when it becomes true.

alice (customer_service, us-west) sees four transactions and two
customers. "Graces" is customers named Grace Hopper: none, until an
approved rename makes one -- a change that reaches a trigger at once
(api/trigger_checks.py).
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import core.trigger_windows
from api.timer_service import Firing, fire_due
from api.trigger_checks import hold_timer, schedule_timer
from core.timers import TimerStore
from core.trigger_states import HOLD_KIND, SCHEDULE_KIND
from tests.integration.test_trigger_checks import _csrf, _inline, _notes

GRACE = [{"field": "name", "operator": "equals", "value": "Grace Hopper"}]
REFUNDS = [{"field": "category", "operator": "equals", "value": "refund"}]


@pytest.fixture
def alice(client):
    client.app.state.user_directory.create_user("alice", "pw", "us-west", "customer_service")
    client.post("/api/login", json={"username": "alice", "password": "pw"})
    _inline(client)
    return client


def _view(client, name, object_type, conditions=()):
    client.post("/api/saved-views", json={"name": name, "object_type": object_type,
                                          "conditions": list(conditions)}, headers=_csrf(client))
    return next(view["view_id"] for view in client.get("/api/saved-views").json()["views"]
                if view["name"] == name)


def _trigger(client, **body):
    return client.post("/api/triggers", json={"name": "Watch", **body}, headers=_csrf(client))


def _rename(client, new_name):
    """An approved change, made by an editor -- alice cannot run the
    action herself -- and then back to alice, whose triggers these are.
    The checker is the app's, so it sees the change whoever made it."""
    if not client.app.state.user_directory.get_user_record("erin").role_name:
        client.app.state.user_directory.create_user("erin", "pw", "us-west", "editor")
    client.post("/api/login", json={"username": "erin", "password": "pw"})
    proposed = client.post("/api/actions/UpdateCustomerName",
                           json={"parameters": {"customer_id": "cust_001", "new_name": new_name}},
                           headers=_csrf(client))
    assert proposed.status_code == 202, proposed.text
    confirmed = client.post(f"/api/writes/{proposed.json()['pending_write']['id']}/confirm",
                            json={"approved": True}, headers=_csrf(client))
    assert confirmed.json().get("status") == "written", confirmed.text
    client.post("/api/login", json={"username": "alice", "password": "pw"})


def _met(client):
    return [note for note in _notes(client) if note.endswith("-- met.")]


class _Clock:
    def __init__(self, monkeypatch, at):
        self.at = at
        monkeypatch.setattr(core.trigger_windows, "now", lambda: self.at)


class TestAllOrAny:
    def test_all_fires_when_the_last_part_becomes_true(self, alice):
        """Transactions above 3 (true) AND Graces above 0 (false): the
        baseline says "not met"; the rename makes it met, and it fires
        once -- reached through the CUSTOMER change although the
        trigger's own view is of transactions."""
        everything = _view(alice, "All transactions", "Transaction")
        graces = _view(alice, "Graces", "Customer", GRACE)
        assert _trigger(alice, view_id=everything, above=3,
                        also=[{"view_id": graces, "above": 0}]).status_code == 200
        assert any("Currently not met" in note for note in _notes(alice))

        _rename(alice, "Grace Hopper")

        assert _met(alice) == ["Watch: All transactions above 3 and Graces above 0 -- met."]

    def test_it_fires_once_while_it_stays_true(self, alice):
        everything = _view(alice, "All transactions", "Transaction")
        graces = _view(alice, "Graces", "Customer", GRACE)
        _trigger(alice, view_id=everything, above=3, also=[{"view_id": graces, "above": 0}])
        _rename(alice, "Grace Hopper")

        _rename(alice, "Grace Hopper")  # still true: a second change, no second notice

        assert len(_met(alice)) == 1

    def test_any_fires_on_either(self, alice):
        refunds = _view(alice, "Refunds", "Transaction", REFUNDS)
        graces = _view(alice, "Graces", "Customer", GRACE)
        _trigger(alice, view_id=refunds, above=5, combine="any", also=[{"view_id": graces, "above": 0}])

        _rename(alice, "Grace Hopper")

        assert _met(alice) == ["Watch: Refunds above 5 or Graces above 0 -- met."]

    def test_already_true_when_made_does_not_fire_for_it(self, alice):
        """The baseline is latched: a crossing that happened before the
        trigger existed is not news. A later change that leaves it true
        says nothing either."""
        graces = _view(alice, "Graces", "Customer", GRACE)
        _trigger(alice, view_id=graces, at_most=0)

        _rename(alice, "Ada O.")

        assert _met(alice) == []

    def test_at_most(self, alice):
        graces = _view(alice, "Graces", "Customer", GRACE)
        _trigger(alice, view_id=graces, at_most=0)

        assert any("Currently met" in note for note in _notes(alice))


class TestHeldForAWhile:
    def test_fires_when_the_hold_ends_not_before(self, alice, monkeypatch):
        clock = _Clock(monkeypatch, datetime(2026, 7, 20, 9, tzinfo=UTC))
        graces = _view(alice, "Graces", "Customer", GRACE)
        trigger_id = _trigger(alice, view_id=graces, above=0, hold_minutes=60).json()["trigger_id"]

        _rename(alice, "Grace Hopper")

        assert _met(alice) == []
        timers = TimerStore(Path(alice.app.state.runtime_paths.data_dir))
        assert timers.get(HOLD_KIND, trigger_id).due_at == (clock.at + timedelta(hours=1)).timestamp()

        clock.at += timedelta(hours=1)
        fire_due(alice.app, {HOLD_KIND: hold_timer}, clock=lambda: clock.at.timestamp())

        assert _met(alice) == ["Watch: Graces above 0, for 1 hour -- met."]

    def test_stopping_being_true_first_resets_it(self, alice, monkeypatch):
        clock = _Clock(monkeypatch, datetime(2026, 7, 20, 9, tzinfo=UTC))
        graces = _view(alice, "Graces", "Customer", GRACE)
        trigger_id = _trigger(alice, view_id=graces, above=0, hold_minutes=60).json()["trigger_id"]
        _rename(alice, "Grace Hopper")
        clock.at += timedelta(minutes=30)

        _rename(alice, "Ada Okafor")

        assert TimerStore(Path(alice.app.state.runtime_paths.data_dir)).get(HOLD_KIND, trigger_id) is None
        clock.at += timedelta(hours=1)
        fire_due(alice.app, {HOLD_KIND: hold_timer}, clock=lambda: clock.at.timestamp())
        assert _met(alice) == []


    def test_true_again_after_a_gap_holds_from_the_new_start(self, alice, monkeypatch):
        """True at 09:00, false at 09:30, true at 09:40: the hour runs
        from 09:40, so the timer is for 10:40, not 10:00."""
        clock = _Clock(monkeypatch, datetime(2026, 7, 20, 9, tzinfo=UTC))
        graces = _view(alice, "Graces", "Customer", GRACE)
        trigger_id = _trigger(alice, view_id=graces, above=0, hold_minutes=60).json()["trigger_id"]
        _rename(alice, "Grace Hopper")
        clock.at += timedelta(minutes=30)
        _rename(alice, "Ada Okafor")
        clock.at += timedelta(minutes=10)

        _rename(alice, "Grace Hopper")

        timer = TimerStore(Path(alice.app.state.runtime_paths.data_dir)).get(HOLD_KIND, trigger_id)
        assert timer.due_at == datetime(2026, 7, 20, 10, 40, tzinfo=UTC).timestamp()


class TestOnASchedule:
    def _scheduled(self, alice):
        graces = _view(alice, "Graces", "Customer", GRACE)
        response = _trigger(alice, view_id=graces, above=0,
                            schedule={"days": [0, 1, 2, 3, 4], "time": "09:00"}, timezone="UTC")
        assert response.status_code == 200, response.text
        return response.json()["trigger_id"]

    def _firing(self, alice, trigger_id, **changes):
        timer = TimerStore(Path(alice.app.state.runtime_paths.data_dir)).get(SCHEDULE_KIND, trigger_id)
        return Firing(timer, timer.due_at, **changes)

    def test_it_sets_its_repeating_check(self, alice):
        trigger_id = self._scheduled(alice)

        timer = TimerStore(Path(alice.app.state.runtime_paths.data_dir)).get(SCHEDULE_KIND, trigger_id)
        assert timer.repeat["days"] == [0, 1, 2, 3, 4] and timer.owner_user_id == "alice"

    def test_a_change_between_checks_tells_nobody(self, alice):
        self._scheduled(alice)

        _rename(alice, "Grace Hopper")

        assert _met(alice) == []

    def test_each_check_while_true_tells_once(self, alice):
        trigger_id = self._scheduled(alice)
        _rename(alice, "Grace Hopper")
        firing = self._firing(alice, trigger_id)

        schedule_timer(alice.app, firing)
        schedule_timer(alice.app, firing)  # delivered twice: one notice

        assert _met(alice) == ["Watch: Graces above 0, checked weekdays at 09:00 (UTC) -- met."]

    def test_a_missed_check_is_said(self, alice):
        trigger_id = self._scheduled(alice)

        schedule_timer(alice.app, self._firing(alice, trigger_id, missed=True))

        assert any("was missed while Elysium was not running" in note for note in _notes(alice))

    def test_turning_it_off_stops_its_check_and_on_sets_it_again(self, alice):
        trigger_id = self._scheduled(alice)
        timers = TimerStore(Path(alice.app.state.runtime_paths.data_dir))

        alice.post(f"/api/triggers/{trigger_id}/enabled?enabled=false", headers=_csrf(alice))
        assert timers.get(SCHEDULE_KIND, trigger_id) is None
        alice.post(f"/api/triggers/{trigger_id}/enabled?enabled=true", headers=_csrf(alice))
        assert timers.get(SCHEDULE_KIND, trigger_id) is not None

    def test_deleting_it_stops_its_check(self, alice):
        trigger_id = self._scheduled(alice)

        alice.delete(f"/api/triggers/{trigger_id}", headers=_csrf(alice))

        assert TimerStore(Path(alice.app.state.runtime_paths.data_dir)).get(SCHEDULE_KIND, trigger_id) is None


class TestRefusedWithTheReason:
    @pytest.mark.parametrize("extra, says", [
        ({"gained": 1, "above": None, "hold_minutes": 10}, "change since the last check"),
        ({"action_view_id": "SELF-ELSEWHERE"}, "chosen, but no action"),
        ({"hold_minutes": 10, "schedule": {"days": [1], "time": "09:00"}}, "cannot also require"),
        ({"hold_minutes": 0}, "Hold for 1 minute"),
        ({"combine": "xor", "also": [{"view_id": "SELF", "above": 1}]}, "all or any"),
        ({"also": [{"view_id": "SELF", "above": 1}] * 10}, "At most 10"),
        ({"also": [{"view_id": "SELF", "above": 1, "at_most": 2}]}, "above or at most"),
        ({"schedule": {"every_minutes": 1}}, "every 5 minutes"),
    ])
    def test_refused(self, alice, extra, says):
        graces = _view(alice, "Graces", "Customer", GRACE)
        body = {"view_id": graces, "above": 0, **extra}
        body["also"] = [{**condition, "view_id": graces} for condition in body.get("also", [])]

        response = _trigger(alice, **body)

        assert response.status_code == 400
        assert says in response.json()["detail"]

    def test_somebody_elses_view_reads_as_none_at_all(self, alice):
        graces = _view(alice, "Graces", "Customer", GRACE)

        response = _trigger(alice, view_id=graces, above=0, also=[{"view_id": "not-mine", "above": 1}])

        assert response.json()["detail"] == "Each condition watches one of your own saved views."


def test_the_list_says_it_in_words(alice):
    everything = _view(alice, "All transactions", "Transaction")
    graces = _view(alice, "Graces", "Customer", GRACE)
    _trigger(alice, view_id=everything, above=3, also=[{"view_id": graces, "at_most": 0}], hold_minutes=120)

    [listed] = alice.get("/api/triggers").json()["triggers"]

    assert listed["description"] == "All transactions above 3 and Graces at most 0, for 2 hours"


def test_a_scheduled_config_yaml_trigger_is_checked_by_its_timer(client):
    """The handler finds a declared trigger in the running configuration
    -- it is not in the store -- and tells its owner at the check."""
    import dataclasses

    from core.declared_triggers import load_declared_triggers
    from core.trigger_states import arm_declared

    client.app.state.user_directory.create_user("alice", "pw", "us-west", "customer_service")
    client.post("/api/login", json={"username": "alice", "password": "pw"})
    generation = client.app.state.generation
    (declared,) = load_declared_triggers(
        [{"name": "Morning refunds", "owner": "alice", "object_type": "Transaction",
          "conditions": REFUNDS, "above": 0, "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "time": "09:00"}}],
        generation.config.schema, generation.config.action_types, generation.config.roles)
    client.app.state.generation = dataclasses.replace(
        generation, config=dataclasses.replace(generation.config, declared_triggers=(declared,)))
    timers = TimerStore(Path(client.app.state.runtime_paths.data_dir))
    arm_declared(timers, (declared,))
    timer = timers.get(SCHEDULE_KIND, declared.trigger_id)

    schedule_timer(client.app, Firing(timer, timer.due_at))  # first look: the baseline
    schedule_timer(client.app, Firing(timer, timer.due_at + 86400, occurrence_at=timer.due_at + 86400))

    assert any(note.startswith("Morning refunds: Morning refunds above 0, checked every day at 09:00 (UTC)")
               for note in _notes(client)), _notes(client)


def test_a_reload_sets_the_check_of_a_scheduled_config_yaml_trigger(client, monkeypatch):
    """config.yaml is where declared triggers are made and unmade, so a
    reload is when their schedules are set -- not the next restart. The
    reload's build is wrapped to add one, as an edited config.yaml would."""
    import dataclasses

    import api.reload
    from core.declared_triggers import load_declared_triggers

    real = api.reload.build_generation

    def with_a_scheduled_trigger(*args, **kwargs):
        built = real(*args, **kwargs)
        (declared,) = load_declared_triggers(
            [{"name": "Morning refunds", "owner": "alice", "object_type": "Transaction",
              "conditions": REFUNDS, "above": 0, "schedule": {"days": [0], "time": "09:00"}}],
            built.config.schema, built.config.action_types, built.config.roles)
        return dataclasses.replace(built, config=dataclasses.replace(built.config,
                                                                     declared_triggers=(declared,)))
    monkeypatch.setattr(api.reload, "build_generation", with_a_scheduled_trigger)

    api.reload.reload_generation(client.app, requested_by="test")

    timers = TimerStore(Path(client.app.state.runtime_paths.data_dir))
    assert timers.get(SCHEDULE_KIND, "declared/Morning refunds") is not None
