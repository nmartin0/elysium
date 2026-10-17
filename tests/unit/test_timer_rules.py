"""When a repeating timer next fires (core/timer_rules.py): intervals
keep to their anchor, weekday rules keep to the owner's clock across a
daylight-saving change, and a rule ends at its `until`."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from core.timer_rules import RuleError, first_occurrence, instant, next_occurrence, validate

NY = ZoneInfo("America/New_York")


def _utc(*args):
    return datetime(*args, tzinfo=UTC)


class TestAnInterval:
    def test_keeps_to_its_anchor_however_late_it_ran(self):
        """Every 2 hours from 09:00, found at 12:40, next is 13:00 --
        not 14:40."""
        rule = {"every_minutes": 120}

        assert next_occurrence(rule, _utc(2026, 7, 20, 12, 40), _utc(2026, 7, 20, 9)) == _utc(2026, 7, 20, 13)

    def test_strictly_after(self):
        rule = {"every_minutes": 60}

        assert next_occurrence(rule, _utc(2026, 7, 20, 10), _utc(2026, 7, 20, 9)) == _utc(2026, 7, 20, 11)

    def test_begins_at_its_start_or_one_interval_from_now(self):
        now = _utc(2026, 7, 20, 9)
        rule = {"every_minutes": 30}

        assert first_occurrence(rule, now) == now + timedelta(minutes=30)
        assert first_occurrence(rule, now, _utc(2026, 7, 21, 8)) == _utc(2026, 7, 21, 8)


class TestAWeekdayRule:
    WEEKDAYS_9 = {"days": [0, 1, 2, 3, 4], "time": "09:00", "timezone": "America/New_York"}

    def test_skips_the_weekend(self):
        friday_ten = datetime(2026, 7, 24, 10, tzinfo=NY)

        assert next_occurrence(self.WEEKDAYS_9, friday_ten, friday_ten) == datetime(2026, 7, 27, 9, tzinfo=NY)

    def test_stays_nine_on_the_owners_clock_across_the_spring_change(self):
        """8 March 2026 the clocks go forward: 09:00 is 14:00 UTC the
        Friday before and 13:00 UTC the Monday after."""
        friday = datetime(2026, 3, 6, 10, tzinfo=NY)
        monday = next_occurrence(self.WEEKDAYS_9, friday, friday)

        assert monday.astimezone(NY).hour == 9
        assert monday == _utc(2026, 3, 9, 13)

    def test_and_across_the_autumn_change(self):
        friday = datetime(2026, 10, 30, 10, tzinfo=NY)
        monday = next_occurrence(self.WEEKDAYS_9, friday, friday)

        assert monday.astimezone(NY).hour == 9
        assert monday == _utc(2026, 11, 2, 14)

    def test_a_time_that_does_not_exist_fires_at_the_first_that_does(self):
        """02:30 on 8 March does not exist in New York; it fires at 03:30."""
        rule = {"days": [6], "time": "02:30", "timezone": "America/New_York"}
        saturday = datetime(2026, 3, 7, 12, tzinfo=NY)

        fires = next_occurrence(rule, saturday, saturday)

        assert fires.astimezone(NY).replace(tzinfo=None) == datetime(2026, 3, 8, 3, 30)

    def test_a_time_that_happens_twice_fires_once_at_the_first(self):
        rule = {"days": [6], "time": "01:30", "timezone": "America/New_York"}
        saturday = datetime(2026, 10, 31, 12, tzinfo=NY)

        first = next_occurrence(rule, saturday, saturday)
        after_it = next_occurrence(rule, first, saturday)

        assert first == _utc(2026, 11, 1, 5, 30)  # 01:30 EDT
        assert after_it.date() == datetime(2026, 11, 8).date()  # a week on, not an hour on


def test_a_rule_ends_at_its_until():
    rule = {"every_minutes": 60, "until": "2026-07-20T11:30:00+00:00"}

    assert next_occurrence(rule, _utc(2026, 7, 20, 10, 5), _utc(2026, 7, 20, 9)) == _utc(2026, 7, 20, 11)
    assert next_occurrence(rule, _utc(2026, 7, 20, 11, 5), _utc(2026, 7, 20, 9)) is None


@pytest.mark.parametrize("rule", [
    {"every_minutes": 4},
    {"every_minutes": 1.5},
    {"days": [], "time": "09:00", "timezone": "UTC"},
    {"days": [7], "time": "09:00", "timezone": "UTC"},
    {"days": [1], "time": "nine", "timezone": "UTC"},
    {"days": [1], "time": "09:00", "timezone": "Mars/Olympus"},
    {"every_minutes": 60, "days": [1]},
    {"every_minutes": 60, "until": "2026-07-20T11:30:00"},
])
def test_a_rule_that_cannot_be_scheduled_is_refused(rule):
    with pytest.raises(RuleError):
        validate(rule)


def test_a_moment_without_an_offset_is_refused_rather_than_guessed():
    with pytest.raises(RuleError, match="no offset"):
        instant("2026-07-20T09:00:00")
    assert instant("2026-07-20T09:00:00Z") == _utc(2026, 7, 20, 9)
