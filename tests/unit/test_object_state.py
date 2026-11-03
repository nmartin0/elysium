"""The state of an object while silver is rebuilt (core/mirror/object_state):
unavailable when it cannot be told, rebuilding only while a sync holds the
lock, the worst of a type's tables for the type."""

import pytest

from core.mirror.object_state import LIVE, REBUILDING, UNAVAILABLE, hold_reason, table_state, type_state


class TestTableState:
    def test_an_unreadable_lake_is_unavailable_whatever_else_is_known(self):
        assert table_state(owed_known=False, last_outcome="rebuilding", sync_running=True) == UNAVAILABLE
        assert table_state(owed_known=False, last_outcome=None, sync_running=False) == UNAVAILABLE

    def test_a_recorded_rebuild_is_rebuilding_only_while_a_sync_runs(self):
        assert table_state(owed_known=True, last_outcome="rebuilding", sync_running=True) == REBUILDING
        assert table_state(owed_known=True, last_outcome="rebuilding", sync_running=False) == LIVE

    def test_a_lock_that_could_not_be_tried_is_unavailable_for_a_recorded_rebuild_only(self):
        assert table_state(owed_known=True, last_outcome="rebuilding", sync_running=None) == UNAVAILABLE
        assert table_state(owed_known=True, last_outcome="synced", sync_running=None) == LIVE

    @pytest.mark.parametrize("outcome", [None, "synced", "unchanged", "degraded", "refused"])
    def test_any_other_attempt_is_live_even_with_a_sync_running(self, outcome):
        assert table_state(owed_known=True, last_outcome=outcome, sync_running=True) == LIVE


class TestTypeState:
    def test_it_is_the_worst_of_its_tables(self):
        assert type_state([LIVE, REBUILDING, LIVE]) == REBUILDING
        assert type_state([LIVE, REBUILDING, UNAVAILABLE]) == UNAVAILABLE
        assert type_state([LIVE, LIVE]) == LIVE

    def test_a_type_reading_no_table_is_live(self):
        assert type_state([]) == LIVE


class TestHoldReason:
    def test_a_live_type_and_a_type_with_no_state_are_not_held(self):
        assert hold_reason({"A": LIVE}, ["A"]) is None
        assert hold_reason({"A": LIVE}, ["B"]) is None

    def test_rebuilding_is_held_and_names_the_type(self):
        reason = hold_reason({"A": REBUILDING, "B": LIVE}, ["A", "B"])

        assert reason is not None and reason.startswith("A is being rebuilt")

    def test_unavailable_is_held_and_says_it_cannot_be_told_even_beside_a_rebuilding_type(self):
        reason = hold_reason({"A": UNAVAILABLE, "B": REBUILDING}, ["A", "B"])

        assert reason is not None and "cannot be told" in reason and "A" in reason

    def test_only_the_types_the_write_touches_count(self):
        assert hold_reason({"A": REBUILDING}, ["B"]) is None
