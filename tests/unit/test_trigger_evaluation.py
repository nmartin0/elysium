"""
Every enabled trigger, run as its own owner.

AS THE OWNER, AND ONLY FOR THE OWNER. A UI-created trigger notifies
the person who made it -- which is what makes it safe to offer
without a new grant. Naming somebody else would be a capability its
creator does not otherwise have.

ONE FAILURE COSTS ONE TRIGGER. A view that was deleted, an owner who
lost a grant, a silo down for one partition -- none should stop the
others.
"""

import pytest

from core.count_condition import evaluate_user_triggers
from core.intermediate_layer.auth import UserRecord
from core.notifications import NotificationStore
from core.saved_views import SavedViewStore
from core.triggers import TriggerStore, describe


@pytest.fixture
def mediator(synced_deployment):
    from core.deployment_loader import build_generation

    # E-08: a deployment of its own, not the developer's.
    paths = synced_deployment
    return build_generation(
        paths.config_dir, paths.data_dir, paths.log_dir,
    ).mediator


@pytest.fixture
def stores(tmp_path):
    return (
        TriggerStore(tmp_path / "t.db"),
        SavedViewStore(tmp_path / "v.db"),
        NotificationStore(tmp_path / "n.db"),
    )


OWNER = UserRecord("debug", "us-west", "debug")
OWNERS = {"debug": OWNER}


def _watching(stores, above=2):
    triggers, views, _ = stores
    view_id = views.save("debug", "All transactions", "Transaction")
    triggers.create("debug", "Transactions", view_id, above=above)
    return view_id


class TestItRuns:
    def test_the_first_run_is_a_baseline(self, mediator, stores):
        triggers, views, notes = stores
        _watching(stores)

        fired = evaluate_user_triggers(
            mediator, triggers, views, notes, OWNERS, "d",
        )

        assert fired == 0
        assert [n.kind for n in notes.for_user("debug")] == [
            "count_condition_watching",
        ]

    def test_a_crossing_fires(self, mediator, stores):
        triggers, views, notes = stores
        _watching(stores)
        evaluate_user_triggers(mediator, triggers, views, notes, OWNERS, "d")
        notes.record_count(
            triggers.all_enabled()[0].condition_key, "debug", 0, "d",
        )

        fired = evaluate_user_triggers(
            mediator, triggers, views, notes, OWNERS, "d",
        )

        assert fired == 1

    def test_the_notification_reads_as_a_sentence(self, mediator, stores):
        """THE DESCRIPTION IS THE ONLY THING A RECIPIENT SEES besides
        their own count, so it must read as something somebody wrote
        rather than as a row."""
        triggers, views, notes = stores
        _watching(stores)
        evaluate_user_triggers(mediator, triggers, views, notes, OWNERS, "d")
        notes.record_count(
            triggers.all_enabled()[0].condition_key, "debug", 0, "d",
        )
        evaluate_user_triggers(mediator, triggers, views, notes, OWNERS, "d")

        alerts = [
            n.summary for n in notes.for_user("debug")
            if n.kind == "count_condition"
        ]

        assert alerts[0].startswith("Transactions above 2")


class TestWhatItSkips:
    def test_a_disabled_trigger_does_not_run(self, mediator, stores):
        triggers, views, notes = stores
        _watching(stores)
        trigger_id = triggers.all_enabled()[0].trigger_id
        triggers.set_enabled("debug", trigger_id, False)

        evaluate_user_triggers(mediator, triggers, views, notes, OWNERS, "d")

        assert notes.for_user("debug") == []

    def test_a_trigger_whose_owner_is_gone_does_not_run(self, mediator, stores):
        """RUNNING IT AS ANYBODY ELSE would be the confused deputy
        this project spends its security budget avoiding."""
        triggers, views, notes = stores
        _watching(stores)

        # SOMEBODY ELSE IS PRESENT, which is what makes this a real
        # test. A first version passed an EMPTY map, so a control
        # substituting "whoever is available" found nobody either and
        # passed unchanged.
        somebody_else = {"other": UserRecord("other", "us-east", "debug")}

        evaluate_user_triggers(
            mediator, triggers, views, notes, somebody_else, "d",
        )

        assert notes.for_user("debug") == []
        assert notes.for_user("other") == []

    def test_a_trigger_whose_view_is_gone_does_not_run(self, mediator, stores):
        triggers, views, notes = stores
        view_id = _watching(stores)
        views.delete("debug", view_id)

        evaluate_user_triggers(mediator, triggers, views, notes, OWNERS, "d")

        assert notes.for_user("debug") == []


class TestEditingATriggerTakesAFreshBaseline:
    def test_the_key_is_the_triggers_own_id(self, stores):
        """A TRIGGER THAT FIRED AT 10 AND NOW FIRES AT 100 should take
        a fresh baseline rather than compare against counts measured
        under a different question."""
        triggers, views, _ = stores
        view_id = views.save("debug", "v", "Transaction")
        first = triggers.create("debug", "a", view_id, above=10)
        second = triggers.create("debug", "b", view_id, above=100)

        keys = {t.condition_key for t in triggers.all_enabled()}

        assert len(keys) == 2
        assert first != second

    def test_the_key_avoids_the_grant_verb_shape(self, stores):
        """THE GRANT-VOCABULARY TEST reads `verb:subject` anywhere in
        the code as a permission being asked for, and "trigger:"
        tripped it. The key avoids the shape rather than the test
        being loosened."""
        triggers, views, _ = stores
        view_id = views.save("debug", "v", "Transaction")
        triggers.create("debug", "a", view_id, above=10)

        assert ":" not in triggers.all_enabled()[0].condition_key


class TestHowATriggerDescribesItself:
    def test_an_above_threshold(self, stores):
        triggers, views, _ = stores
        view_id = views.save("debug", "v", "Transaction")
        triggers.create("debug", "Open tickets", view_id, above=10)

        assert describe(triggers.all_enabled()[0]) == "Open tickets above 10"

    def test_a_gain(self, stores):
        triggers, views, _ = stores
        view_id = views.save("debug", "v", "Transaction")
        triggers.create("debug", "New rows", view_id, gained=3)

        assert describe(triggers.all_enabled()[0]) == "New rows gaining 3 or more"
