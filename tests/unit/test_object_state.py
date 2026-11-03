"""The state of an object while silver is rebuilt (core/mirror/object_state):
unavailable when it cannot be told, rebuilding only while a sync holds the
lock, the worst of a type's tables for the type."""

import pytest

from core.mirror.object_state import LIVE, REBUILDING, UNAVAILABLE, table_state, type_state


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
