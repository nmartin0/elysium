"""A relative date in hours (16 October): "in the last 4 hours".

The SAME operator in a second unit, so every reader goes through one
helper -- core/filters.relative_window -- and none can quietly read days
alone.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core.agent.set_context import condition_clause
from core.filters import FieldFilter, FilterError, relative_window, resolve_relative_date, validate_filter
from core.saved_views import SavedView
from core.trigger_windows import next_crossing

NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)


def _hours(**value):
    return FieldFilter("opened", "relative_date", value)


class TestValidation:
    @pytest.mark.parametrize("value", [{"since_hours_ago": 4}, {"until_hours_ago": 4},
                                       {"since_hours_ago": 8, "until_hours_ago": 4}])
    def test_hours_are_accepted_on_a_timestamp(self, value):
        validate_filter(_hours(**value), "timestamp")

    def test_days_and_hours_together_are_refused(self):
        with pytest.raises(FilterError, match="days or in hours, not both"):
            validate_filter(_hours(since_days_ago=1, until_hours_ago=4), "timestamp")

    def test_hours_on_a_date_are_refused_by_name(self):
        """A date has no time of day; answering in hours anyway would be
        a wrong answer reported as a right one."""
        with pytest.raises(FilterError, match="is a date, with no time of day"):
            validate_filter(_hours(since_hours_ago=4), "date")

    def test_days_on_a_date_are_still_fine(self):
        validate_filter(_hours(since_days_ago=4), "date")

    @pytest.mark.parametrize("bad", [1.5, -1, True, "4"])
    def test_a_whole_number_of_hours(self, bad):
        with pytest.raises(FilterError, match="hours"):
            validate_filter(_hours(since_hours_ago=bad), "timestamp")

    def test_a_window_that_matches_nothing_is_refused(self):
        with pytest.raises(FilterError, match="matches nothing"):
            validate_filter(_hours(since_hours_ago=2, until_hours_ago=4), "timestamp")


class TestOneHelperForEveryReader:
    def test_the_window_is_in_the_unit_it_counts(self):
        assert relative_window({"since_hours_ago": 4}) == (timedelta(hours=4), None)
        assert relative_window({"until_days_ago": 2}) == (None, timedelta(days=2))

    def test_resolved_in_hours(self):
        assert resolve_relative_date({"since_hours_ago": 4}, NOW) == {
            "start": "2026-07-20T08:00:00+00:00", "end": None}

    def test_the_agent_says_hours(self):
        fields = {"opened": {"display_name": "Opened"}}

        assert condition_clause(_hours(since_hours_ago=4), fields) == "whose Opened is within the last 4 hours"
        assert condition_clause(_hours(until_days_ago=2), fields) == "whose Opened is more than 2 days ago"

    def test_a_trigger_wakes_when_a_record_turns_n_hours_old(self):
        class Earliest:
            def aggregate_by_field(self, *args, **kwargs):
                return {None: "2026-07-20T09:30:00+00:00"}

        view = SavedView("v", "Open", "Ticket", "", [
            {"field": "opened", "operator": "relative_date", "value": {"since_hours_ago": 4}}], {}, "")

        assert next_crossing(Earliest(), view, [object()], NOW) == datetime(2026, 7, 20, 13, 30, tzinfo=UTC)
