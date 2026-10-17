"""config.yaml triggers may be combined, held and scheduled too (17
October; core/declared_triggers.py) -- the same rules a trigger made in
the Watch dialog meets, so neither can say what the other cannot.

    triggers:
      - name: Refunds while busy
        owner: ops-bot
        object_type: Transaction
        above: 2
        also:
          - name: Refunds
            object_type: Transaction
            conditions: [{field: category, operator: equals, value: refund}]
            above: 0
        combine: all
        hold_minutes: 60
        action: {type: RecategorizeTransactions, parameter: transaction_ids,
                 values: {new_category: flagged}, objects_from: Refunds}
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import core.trigger_windows
from core.declared_triggers import load_declared_triggers
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore
from core.timers import TimerStore
from core.trigger_runs import run_triggers
from core.trigger_states import SCHEDULE_KIND, State, TriggerStateStore, arm_declared
from core.user_directory import UserDirectory

REFUNDS = {"name": "Refunds", "object_type": "Transaction",
           "conditions": [{"field": "category", "operator": "equals", "value": "refund"}], "above": 0}
ACTION = {"type": "RecategorizeTransactions", "parameter": "transaction_ids",
          "values": {"new_category": "flagged"}}


@pytest.fixture
def generation(synced_deployment):
    from core.deployment_loader import build_generation

    paths = synced_deployment
    return build_generation(paths.config_dir, paths.data_dir, paths.log_dir)


def _load(generation, entries):
    return load_declared_triggers(entries, generation.config.schema, generation.config.action_types,
                                  generation.config.roles)


def _entry(**overrides):
    return {"name": "Refunds while busy", "owner": "ops-bot", "object_type": "Transaction",
            "above": 2, **overrides}


class TestItParses:
    def test_conditions_combine_hold_and_where_the_action_takes_its_objects(self, generation):
        (trigger,) = _load(generation, [_entry(also=[REFUNDS], combine="any", hold_minutes=60,
                                               action={**ACTION, "objects_from": "Refunds"})])

        assert trigger.combine == "any" and trigger.hold_minutes == 60
        assert [view.name for view in trigger.more_views] == ["Refunds"]
        assert trigger.also == ({"view_id": "declared/Refunds while busy/1", "above": 0},)
        assert trigger.action_view_id == "declared/Refunds while busy/1"

    def test_a_schedule_in_its_zone(self, generation):
        (trigger,) = _load(generation, [_entry(schedule={"days": [0, 1, 2, 3, 4], "time": "09:00"},
                                               timezone="Europe/London")])

        assert trigger.schedule == {"days": [0, 1, 2, 3, 4], "time": "09:00", "timezone": "Europe/London"}

    def test_at_most(self, generation):
        (trigger,) = _load(generation, [_entry(above=None, at_most=0)])

        assert trigger.at_most == 0


class TestRefusedAtLoad:
    @pytest.mark.parametrize("change, says", [
        ({"also": [{**REFUNDS, "colour": "red"}]}, "unknown key"),
        ({"also": [{**REFUNDS, "object_type": "Nope"}]}, "no object type"),
        ({"also": [REFUNDS, REFUNDS]}, "used twice"),
        ({"also": [REFUNDS], "action": {**ACTION, "objects_from": "Elsewhere"}}, "not one of its conditions"),
        ({"above": None, "gained": 1, "also": [REFUNDS]}, "change since the last check"),
        ({"timezone": "Europe/London"}, "a timezone is for a schedule"),
        ({"schedule": {"every_minutes": 1}}, "every 5 minutes"),
        ({"hold_minutes": 10, "schedule": {"days": [1], "time": "09:00"}}, "cannot also require"),
    ])
    def test_each(self, generation, change, says):
        with pytest.raises(ValueError, match=says):
            _load(generation, [_entry(**change)])

    def test_an_action_on_a_condition_of_the_wrong_type(self, generation):
        """The parameter takes Transactions; objects from a Customer
        condition cannot fill it -- checked against THAT condition."""
        customers = {"name": "Customers", "object_type": "Customer", "above": 0}

        with pytest.raises(ValueError, match="takes Transaction objects"):
            _load(generation, [_entry(also=[customers], action={**ACTION, "objects_from": "Customers"})])


class TestItRuns:
    """Through run_triggers, as the sync and the server run it."""

    def _world(self, tmp_path, generation, synced_deployment, trigger, monkeypatch):
        clock = {"at": datetime(2026, 7, 20, 9, tzinfo=UTC)}
        monkeypatch.setattr(core.trigger_windows, "now", lambda: clock["at"])
        data_dir = Path(synced_deployment.data_dir)
        UserDirectory(data_dir / "credentials.db", generation.config.roles).create_user(
            "ops-bot", "pw-not-used", "us-west", "debug")
        queue = PendingWriteStore(ttl=timedelta(minutes=15),
                                  persistence=PendingWritePersistence(tmp_path / "pending.db"))
        config = dataclasses.replace(generation.config, declared_triggers=(trigger,))

        def run():
            return run_triggers(config, data_dir, generation.mediator,
                                lambda: (generation.mediator, generation.write_mediator, queue))
        return clock, run, queue, TriggerStateStore(data_dir)

    def test_held_and_combined_it_proposes_on_the_named_conditions_objects(
            self, tmp_path, generation, synced_deployment, monkeypatch):
        (trigger,) = _load(generation, [_entry(also=[REFUNDS], hold_minutes=60,
                                               action={**ACTION, "objects_from": "Refunds"})])
        clock, run, queue, states = self._world(tmp_path, generation, synced_deployment, trigger, monkeypatch)
        run()  # the baseline
        states.put(trigger.trigger_id, "ops-bot", State(False, None, False, generation.config.source_digest))

        run()
        assert queue.awaiting(lambda p: True) == []
        clock["at"] += timedelta(hours=1)
        run()

        [(_, pending)] = queue.awaiting(lambda p: True)
        assert pending.user_id == "ops-bot" and len(pending.sub_writes) == 1


class TestItsScheduleIsSet:
    def test_set_left_alone_moved_and_cancelled_with_config_yaml(self, tmp_path, generation):
        (weekdays,) = _load(generation, [_entry(schedule={"days": [0, 1, 2, 3, 4], "time": "09:00"})])
        timers = TimerStore(tmp_path)
        now = datetime(2026, 7, 20, 10, tzinfo=UTC)

        arm_declared(timers, (weekdays,), now)
        first = timers.get(SCHEDULE_KIND, weekdays.trigger_id)
        assert first is not None

        arm_declared(timers, (weekdays,), now + timedelta(days=1))  # a reload a day on, nothing changed
        assert timers.get(SCHEDULE_KIND, weekdays.trigger_id).due_at == first.due_at

        (mondays,) = _load(generation, [_entry(schedule={"days": [0], "time": "07:00"})])
        arm_declared(timers, (mondays,), now)  # the rule changed in config.yaml
        assert timers.get(SCHEDULE_KIND, weekdays.trigger_id).repeat["days"] == [0]

        arm_declared(timers, (), now)  # removed from config.yaml
        assert timers.get(SCHEDULE_KIND, weekdays.trigger_id) is None
