"""
A trigger may notify a role, each member counted as themselves.

FOUNDRY'S RULE, TRANSLATED. Its recipient picker "will only display
users and groups for which the person configuring the Action has
adequate permissions". In Elysium a group is a ROLE, and role names are
visible only to manage:users holders -- so anybody may name a role
THEY HOLD, and a manage:users holder may name ANY role.

EACH MEMBER COUNTED WITH THEIR OWN AUTHORITY. Foundry: "notification
effects use each recipient's individual permissions", so an automation
"may trigger for some recipients but not others".

AND THE ACTION HANGS ON THE OWNER ALONE. Foundry: "condition
evaluation uses automation owner's permissions". A recipient who can
see MORE than the owner may cross while the owner has not -- they are
told, and no write is proposed in the owner's name.
"""

from datetime import timedelta

import pytest

from core.count_condition import evaluate_user_triggers
from core.intermediate_layer.auth import UserRecord
from core.notifications import NotificationStore
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore
from core.saved_views import SavedViewStore
from core.triggers import TriggerStore, recipient_problem

ROLES = {"analyst": {}, "reviewer": {}, "executive": {}}


class TestWhoMayBeNamed:
    def test_a_role_you_hold(self):
        assert recipient_problem(["analyst"], ROLES, "analyst", False) is None

    def test_not_a_role_you_do_not_hold(self):
        """NOBODY NAMES A ROLE THEY COULD NOT OTHERWISE LEARN EXISTS."""
        assert recipient_problem(["executive"], ROLES, "analyst", False)

    def test_any_role_with_manage_users(self):
        # A manage:users holder can already see every role, via /config.
        assert recipient_problem(["executive"], ROLES, "analyst", True) is None

    def test_an_unknown_role_is_refused(self):
        """REFUSED, NOT ACCEPTED AND MATCHED AGAINST NOBODY: silently
        notifying no one reads as a quiet trigger rather than a
        mistyped name."""
        assert recipient_problem(["nonexistent"], ROLES, "analyst", True)

    def test_hidden_and_absent_read_the_same(self):
        """SAYING WHICH would reveal that a role by that name exists."""
        hidden = recipient_problem(["executive"], ROLES, "analyst", False)
        absent = recipient_problem(["nonexistent"], ROLES, "analyst", False)

        assert hidden.replace("executive", "X") == absent.replace("nonexistent", "X")

    def test_a_creator_with_no_role_may_name_none(self):
        assert recipient_problem(["analyst"], ROLES, None, False)


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
    view_id = views.save("owner", "All transactions", "Transaction")
    return generation, views, triggers, notes, queue, view_id


def _run(world, users):
    generation, views, triggers, notes, queue, _ = world
    return evaluate_user_triggers(
        generation.mediator, triggers, views, notes, users, "d",
        generation.write_mediator, queue,
    )


class TestRoleMembersAreNotified:
    def test_each_member_gets_their_own_baseline(self, world):
        """ONE NOTICE PER MEMBER, each from their own evaluation."""
        _, _, triggers, notes, _, view_id = world
        triggers.create("owner", "Watch", view_id, above=2,
                        recipient_roles=["debug"])
        users = {
            "owner": UserRecord("owner", "us-west", "debug"),
            "colleague": UserRecord("colleague", "us-west", "debug"),
        }

        _run(world, users)

        assert notes.for_user("colleague")

    def test_a_member_of_another_role_is_not(self, world):
        _, _, triggers, notes, _, view_id = world
        triggers.create("owner", "Watch", view_id, above=2,
                        recipient_roles=["debug"])
        users = {
            "owner": UserRecord("owner", "us-west", "debug"),
            "outsider": UserRecord("outsider", "us-west", "other"),
        }

        _run(world, users)

        assert notes.for_user("outsider") == []


class TestTheActionHangsOnTheOwner:
    def test_a_recipient_crossing_alone_proposes_nothing(self, world):
        """THE PROPERTY FOUNDRY'S SPLIT EXISTS FOR.

        The owner sees us-east's two transactions and never crosses
        above 2; a us-west colleague sees four and does. The colleague
        is told -- and nothing is proposed in the owner's name, because
        the owner's condition did not fire.
        """
        _, _, triggers, notes, queue, view_id = world
        triggers.create(
            "owner", "Watch", view_id, above=2,
            action_type="RecategorizeTransactions",
            action_parameter="transaction_ids",
            action_values={"new_category": "reviewed"},
            recipient_roles=["debug"],
        )
        users = {
            "owner": UserRecord("owner", "us-east", "debug"),
            "colleague": UserRecord("colleague", "us-west", "debug"),
        }
        _run(world, users)
        key = triggers.all_enabled()[0].condition_key
        notes.record_count(key, "owner", 0, "d")
        notes.record_count(key, "colleague", 0, "d")

        _run(world, users)

        colleague_alerts = [
            n for n in notes.for_user("colleague") if n.kind == "count_condition"
        ]
        assert colleague_alerts
        assert queue.awaiting(lambda p: True) == []

    def test_the_owner_crossing_does_propose(self, world):
        """THE CONTROL. Without it, "nothing is proposed" above would
        pass for an evaluator that never proposed at all."""
        _, _, triggers, notes, queue, view_id = world
        triggers.create(
            "owner", "Watch", view_id, above=2,
            action_type="RecategorizeTransactions",
            action_parameter="transaction_ids",
            action_values={"new_category": "reviewed"},
        )
        users = {"owner": UserRecord("owner", "us-west", "debug")}
        _run(world, users)
        notes.record_count(triggers.all_enabled()[0].condition_key, "owner", 0, "d")

        _run(world, users)

        assert len(queue.awaiting(lambda p: True)) == 1
