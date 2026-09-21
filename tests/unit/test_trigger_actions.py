"""
A trigger that proposes a write when its condition fires.

FOUNDRY ALLOWS IT, and Elysium is more conservative than Foundry.
Any creator of an automation may add an action effect; the gate is the
action's own -- "the owner configuring an action must pass the
submission criteria for that action". Foundry then EXECUTES it.
Elysium PROPOSES it into the approvals queue, where somebody still
decides.

AS THE OWNER, which is what keeps it attenuated: a trigger grants
nothing its owner lacks.

AND ONLY WHEN THE CONDITION FIRED -- never on a baseline, never on a
repeat the notification suppressed.
"""

from datetime import timedelta

import pytest

from core.count_condition import evaluate_user_triggers
from core.intermediate_layer.auth import UserRecord
from core.notifications import NotificationStore
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore
from core.saved_views import SavedViewStore
from core.triggers import TriggerStore, action_problem

OWNER = UserRecord("debug", "us-west", "debug")


@pytest.fixture
def generation():
    from core.deployment_loader import build_generation, resolve_runtime_paths

    paths = resolve_runtime_paths()
    return build_generation(paths.config_dir, paths.data_dir, paths.log_dir)


@pytest.fixture
def world(tmp_path, generation):
    views = SavedViewStore(tmp_path / "v.db")
    triggers = TriggerStore(tmp_path / "t.db")
    notes = NotificationStore(tmp_path / "n.db")
    queue = PendingWriteStore(
        ttl=timedelta(minutes=15),
        persistence=PendingWritePersistence(tmp_path / "pending.db"),
    )
    view_id = views.save("debug", "All transactions", "Transaction")
    triggers.create(
        "debug", "Recategorise", view_id, above=2,
        action_type="RecategorizeTransactions",
        action_parameter="transaction_ids",
        action_values={"new_category": "reviewed"},
    )

    def evaluate():
        return evaluate_user_triggers(
            generation.mediator, triggers, views, notes, {"debug": OWNER},
            "d", generation.write_mediator, queue,
        )

    def cross():
        notes.record_count(triggers.all_enabled()[0].condition_key, "debug", 0, "d")

    return evaluate, cross, queue


class TestItProposesWhenItFires:
    def test_nothing_is_proposed_on_the_baseline(self, world):
        """THE FIRST EVALUATION IS A BASELINE. Proposing on it would
        act on every object that already matched the day the trigger
        was made."""
        evaluate, _, queue = world

        evaluate()

        assert queue.awaiting(lambda p: True) == []

    def test_a_crossing_proposes(self, world):
        evaluate, cross, queue = world
        evaluate()
        cross()

        evaluate()

        assert len(queue.awaiting(lambda p: True)) == 1

    def test_the_proposal_says_a_condition_made_it(self, world):
        evaluate, cross, queue = world
        evaluate()
        cross()
        evaluate()

        _, pending = queue.awaiting(lambda p: True)[0]

        assert pending.origin == "automation"
        assert pending.user_id == OWNER.user_id

    def test_a_suppressed_repeat_proposes_nothing_more(self, world):
        """`told` DECIDES, because it already means "fired". A second
        definition would be two places to disagree -- and would propose
        again on a condition the notification had judged a repeat."""
        evaluate, cross, queue = world
        evaluate()
        cross()
        evaluate()

        evaluate()

        assert len(queue.awaiting(lambda p: True)) == 1


class TestActionValidation:
    def _check(self, generation, **overrides):
        args = {
            "action_type": "RecategorizeTransactions",
            "action_parameter": "transaction_ids",
            "action_values": {"new_category": "x"},
            "owner_may_execute": True,
        }
        args.update(overrides)
        return action_problem(
            generation.config.action_types, "Transaction",
            args["action_type"], args["action_parameter"],
            args["action_values"], args["owner_may_execute"],
        )

    def test_a_valid_action_passes(self, generation):
        assert self._check(generation) is None

    def test_an_unknown_action_is_refused(self, generation):
        assert "No action type" in self._check(generation, action_type="Nope")

    def test_an_owner_who_cannot_run_it_is_refused(self, generation):
        """A TRIGGER GRANTS NOTHING ITS OWNER LACKS. Foundry: "the
        owner configuring an action must pass the submission criteria
        for that action"."""
        assert "cannot run" in self._check(generation, owner_may_execute=False)

    def test_a_parameter_that_does_not_take_objects_is_refused(self, generation):
        problem = self._check(generation, action_parameter="new_category")

        assert "does not take objects" in problem

    def test_a_parameter_for_another_type_is_refused(self, generation):
        problem = action_problem(
            generation.config.action_types, "Customer",
            "RecategorizeTransactions", "transaction_ids", {}, True,
        )

        assert "this view matches Customer" in problem

    def test_an_unknown_value_is_refused(self, generation):
        problem = self._check(generation, action_values={"nonsense": 1})

        assert "no parameter" in problem

    def test_a_value_for_the_matched_parameter_is_refused(self, generation):
        """THE MATCHES FILL IT. A fixed value as well would be silently
        overwritten when the trigger fires."""
        problem = self._check(
            generation,
            action_values={"transaction_ids": ["1"], "new_category": "x"},
        )

        assert "filled by the view" in problem

    def test_an_action_refusing_automation_is_refused(self, generation):
        """CHECKED AT CREATION as well as at proposal: a trigger that
        could never propose would sit failing silently at 3am."""
        action_types = {
            name: {**definition, "automatable": False}
            for name, definition in generation.config.action_types.items()
        }
        problem = action_problem(
            action_types, "Transaction", "RecategorizeTransactions",
            "transaction_ids", {}, True,
        )

        assert "automatable: false" in problem
