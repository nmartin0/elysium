"""
Triggers a deployment declares in config.yaml.

NOT MORE POWERFUL THAN ONE A PERSON MAKES. Foundry's analogue of
"declared centrally" is an automation owned by a SERVICE USER, which
runs with "the service user's permissions" -- its own grants, nothing
extra. So a declared trigger names an owner and runs as that owner,
through the same evaluator a made trigger uses.

VALIDATED AT LOAD, so a mistake stops the deployment starting where
whoever wrote it is looking, rather than surfacing when it was meant
to fire.
"""

from datetime import timedelta

import pytest

from core.count_condition import evaluate_one_trigger
from core.declared_triggers import load_declared_triggers
from core.intermediate_layer.auth import UserRecord
from core.notifications import NotificationStore
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore


@pytest.fixture
def generation():
    from core.deployment_loader import build_generation, resolve_runtime_paths

    paths = resolve_runtime_paths()
    return build_generation(paths.config_dir, paths.data_dir, paths.log_dir)


def _load(generation, entries):
    return load_declared_triggers(
        entries, generation.config.schema, generation.config.action_types,
        generation.config.roles,
    )


def _entry(**overrides):
    entry = {
        "name": "High value",
        "owner": "ops-bot",
        "object_type": "Transaction",
        "above": 2,
    }
    entry.update(overrides)
    return entry


class TestAValidBlock:
    def test_it_parses(self, generation):
        (trigger,) = _load(generation, [_entry()])

        assert trigger.owner_user_id == "ops-bot"
        assert trigger.view.object_type == "Transaction"

    def test_no_block_is_no_triggers(self, generation):
        assert _load(generation, None) == ()

    def test_it_takes_an_action(self, generation):
        (trigger,) = _load(generation, [_entry(action={
            "type": "RecategorizeTransactions",
            "parameter": "transaction_ids",
            "values": {"new_category": "flagged"},
        })])

        assert trigger.action_type == "RecategorizeTransactions"

    def test_its_key_avoids_the_grant_verb_shape(self, generation):
        (trigger,) = _load(generation, [_entry()])

        assert ":" not in trigger.condition_key


class TestMistakesStopTheLoad:
    @pytest.mark.parametrize(("change", "expected"), [
        ({"owner": ""}, "needs an `owner`"),
        ({"object_type": "Nope"}, "no object type"),
        ({"above": None}, "exactly one of"),
        ({"gained": 3}, "exactly one of"),
        ({"above": -1}, "whole number"),
        ({"above": True}, "whole number"),
        ({"recipient_roles": ["no_such_role"]}, "no role"),
        ({"recipient_role": ["x"]}, "unknown key"),
    ])
    def test_each_is_refused(self, generation, change, expected):
        """A MISSPELT `recipient_role` SILENTLY IGNORED would notify
        nobody and read as a quiet trigger, so unknown keys are
        refused rather than skipped."""
        with pytest.raises(ValueError, match=expected):
            _load(generation, [_entry(**change)])

    def test_two_of_one_name_are_refused(self, generation):
        """THE NAME IS THE KEY for its notification state, so two of
        one name would share -- and corrupt -- one baseline."""
        with pytest.raises(ValueError, match="declared twice"):
            _load(generation, [_entry(), _entry()])

    def test_a_malformed_action_is_refused(self, generation):
        with pytest.raises(ValueError, match="does not take objects"):
            _load(generation, [_entry(action={
                "type": "RecategorizeTransactions",
                "parameter": "new_category",
            })])


class TestItRunsAsItsOwner:
    def _world(self, tmp_path, generation, trigger):
        notes = NotificationStore(tmp_path / "n.db")
        queue = PendingWriteStore(
            ttl=timedelta(minutes=15),
            persistence=PendingWritePersistence(tmp_path / "pending.db"),
        )

        def evaluate(users):
            return evaluate_one_trigger(
                trigger, trigger.view, generation.mediator, notes, users, "d",
                generation.write_mediator, queue,
            )
        return evaluate, notes, queue

    def test_a_service_account_owner_is_told(self, tmp_path, generation):
        (trigger,) = _load(generation, [_entry()])
        evaluate, notes, _ = self._world(tmp_path, generation, trigger)
        bot = {"ops-bot": UserRecord("ops-bot", "us-west", "debug")}

        evaluate(bot)
        notes.record_count(trigger.condition_key, "ops-bot", 0, "d")
        evaluate(bot)

        kinds = [n.kind for n in notes.for_user("ops-bot")]
        assert "count_condition" in kinds

    def test_an_owner_who_does_not_exist_runs_nothing(self, tmp_path, generation):
        """THE SERVICE ACCOUNT NAMED IN config.yaml WAS NEVER CREATED --
        the usual reason. Running it as anybody else would be the
        confused deputy, so it runs as nobody."""
        (trigger,) = _load(generation, [_entry()])
        evaluate, notes, _ = self._world(tmp_path, generation, trigger)
        somebody_else = {"alice": UserRecord("alice", "us-west", "debug")}

        assert evaluate(somebody_else) == 0
        assert notes.for_user("alice") == []

    def test_it_proposes_as_its_owner(self, tmp_path, generation):
        """THE SAME ACTION PATH A MADE TRIGGER USES -- as the owner, into
        the approvals queue, never executed."""
        (trigger,) = _load(generation, [_entry(action={
            "type": "RecategorizeTransactions",
            "parameter": "transaction_ids",
            "values": {"new_category": "flagged"},
        })])
        evaluate, notes, queue = self._world(tmp_path, generation, trigger)
        bot = {"ops-bot": UserRecord("ops-bot", "us-west", "debug")}
        evaluate(bot)
        notes.record_count(trigger.condition_key, "ops-bot", 0, "d")

        evaluate(bot)

        (_, pending), = queue.awaiting(lambda p: True)
        assert pending.user_id == "ops-bot"
        assert pending.origin == "automation"


def test_the_shipped_deployment_still_loads(generation):
    """NO BLOCK IN THE SHIPPED config.yaml, and the field defaults."""
    assert generation.config.declared_triggers == ()
