"""Combined, held and scheduled triggers propose actions too (17
October; core/trigger_states.py).

The owner: "isn't that the main point of the triggers?" Foundry's
answer to which objects: an action parameter takes the objects a
CONDITION exposes, of the matching type. So the maker names which
condition's view supplies them -- the trigger's own by default -- and
the proposal is made AS THE OWNER, when THE OWNER's state fires, on what
that view matches now, less what this automation already has waiting.
"""

from datetime import UTC, datetime, timedelta

import pytest

import core.trigger_windows
from core.count_condition import evaluate_user_triggers
from core.intermediate_layer.auth import UserRecord
from core.notifications import NotificationStore
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore
from core.saved_views import SavedViewStore
from core.trigger_states import State, TriggerStateStore, problem
from core.triggers import TriggerStore

OWNER = UserRecord("debug", "us-west", "debug")
REFUNDS = [{"field": "category", "operator": "equals", "value": "refund"}]
ACTION = {"action_type": "RecategorizeTransactions", "action_parameter": "transaction_ids",
          "action_values": {"new_category": "reviewed"}}


@pytest.fixture
def generation(synced_deployment):
    from core.deployment_loader import build_generation

    paths = synced_deployment
    return build_generation(paths.config_dir, paths.data_dir, paths.log_dir)


@pytest.fixture
def world(tmp_path, generation, monkeypatch):
    clock = {"at": datetime(2026, 7, 20, 9, tzinfo=UTC)}
    monkeypatch.setattr(core.trigger_windows, "now", lambda: clock["at"])
    views = SavedViewStore(tmp_path / "v.db")
    triggers = TriggerStore(tmp_path / "t.db")
    notes = NotificationStore(tmp_path / "n.db")
    states = TriggerStateStore(tmp_path)
    queue = PendingWriteStore(ttl=timedelta(minutes=15),
                              persistence=PendingWritePersistence(tmp_path / "pending.db"))
    everything = views.save("debug", "All transactions", "Transaction")
    refunds = views.save("debug", "Refunds", "Transaction", conditions=REFUNDS)

    def evaluate(on_schedule=None):
        return evaluate_user_triggers(generation.mediator, triggers, views, notes,
                                      {"debug": OWNER}, "d", generation.write_mediator, queue,
                                      states=states, on_schedule=on_schedule)

    def not_yet_true():
        """As if the combination had been false at the last check, so
        the next evaluation is a crossing rather than the baseline."""
        trigger = triggers.all_enabled()[0]
        states.put(trigger.trigger_id, "debug", State(False, None, False, "d"))

    def proposed():
        return [pending for _, pending in queue.awaiting(lambda p: True)]

    return {"clock": clock, "triggers": triggers, "evaluate": evaluate, "not_yet_true": not_yet_true,
            "proposed": proposed, "everything": everything, "refunds": refunds}


class TestWhenItProposes:
    def test_not_on_the_baseline(self, world):
        world["triggers"].create("debug", "Held", world["everything"], above=2, hold_minutes=60, **ACTION)

        world["evaluate"]()

        assert world["proposed"]() == []

    def test_when_the_owners_hold_completes_and_not_before(self, world):
        world["triggers"].create("debug", "Held", world["everything"], above=2, hold_minutes=60, **ACTION)
        world["evaluate"]()
        world["not_yet_true"]()

        world["evaluate"]()
        assert world["proposed"]() == []

        world["clock"]["at"] += timedelta(hours=1)
        world["evaluate"]()

        [pending] = world["proposed"]()
        assert pending.origin == "automation" and pending.user_id == "debug"

    def test_on_the_chosen_conditions_objects(self, world):
        """All transactions above 2 AND Refunds above 0, the action on
        REFUNDS: what is proposed is the refund, not every transaction."""
        world["triggers"].create("debug", "Both", world["everything"], above=2,
                                 also=[{"view_id": world["refunds"], "above": 0}],
                                 action_view_id=world["refunds"], **ACTION)
        world["evaluate"]()
        world["not_yet_true"]()

        world["evaluate"]()

        [pending] = world["proposed"]()
        assert len(pending.sub_writes) == 1

    def test_on_its_own_view_by_default(self, world):
        world["triggers"].create("debug", "Both", world["everything"], above=2,
                                 also=[{"view_id": world["refunds"], "above": 0}], **ACTION)
        world["evaluate"]()
        world["not_yet_true"]()

        world["evaluate"]()

        [pending] = world["proposed"]()
        assert len(pending.sub_writes) > 1

    def test_at_each_scheduled_check_while_true_but_not_again_for_what_waits(self, world):
        """A daily check proposes what is new -- R50: nothing this
        automation already has waiting is proposed twice."""
        world["triggers"].create("debug", "Daily", world["refunds"], above=0,
                                 schedule={"days": [0, 1, 2, 3, 4], "time": "09:00", "timezone": "UTC"},
                                 **ACTION)
        world["evaluate"]()  # the baseline, between checks

        world["evaluate"](on_schedule="timer/trigger.schedule/x/1.0")
        world["evaluate"](on_schedule="timer/trigger.schedule/x/2.0")

        assert len(world["proposed"]()) == 1


class TestWhatMayBeChosen:
    BASE = {"above": 1, "gained": None, "fell": None, "at_most": None, "combine": "all",
            "hold_minutes": None, "schedule": None, "view_id": "a", "owned_view_ids": {"a", "b", "c"}}

    def test_one_of_its_own_conditions(self):
        assert problem(**self.BASE, also=[{"view_id": "b", "above": 0}],
                       action_type="X", action_view="b") is None

    def test_not_some_other_view_even_of_its_owner(self):
        says = problem(**self.BASE, also=[{"view_id": "b", "above": 0}], action_type="X", action_view="c")

        assert says == "An action takes its objects from one of this trigger's own conditions."

    def test_not_on_a_single_trigger_either(self):
        """Checked before anything returns early: a single trigger naming
        another view would act on something it does not watch."""
        says = problem(**self.BASE, also=[], action_type="X", action_view="c")

        assert says == "An action takes its objects from one of this trigger's own conditions."
