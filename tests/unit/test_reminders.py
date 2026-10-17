"""A person's reminders (core/reminders.py): what a request may ask
for, what the notice says, and that a firing delivered twice is one
notice."""

from datetime import UTC, datetime

import pytest

from api.timer_service import Firing
from core.notifications import NotificationStore
from core.reminders import ReminderError, describe_repeat, fire, parse
from core.timers import Timer

NOW = datetime(2026, 7, 20, 12, tzinfo=UTC)


class TestWhatMayBeAskedFor:
    def test_a_one_off(self):
        spec = parse({"label": "Call Ada", "at": "2026-07-20T15:00:00+02:00"}, NOW)

        assert spec.due_at == datetime(2026, 7, 20, 13, tzinfo=UTC).timestamp()
        assert spec.repeat is None and spec.late_after == 3600.0

    def test_weekdays_at_nine_keep_to_the_owners_zone(self):
        spec = parse({"label": "Stand-up", "repeat": {"days": [0, 1, 2, 3, 4], "time": "09:00"},
                      "timezone": "Europe/London"}, NOW)

        assert spec.repeat["timezone"] == "Europe/London"
        assert spec.due_at == datetime(2026, 7, 21, 8, tzinfo=UTC).timestamp()  # 09:00 BST

    def test_deliver_however_late(self):
        spec = parse({"label": "x", "at": "2026-07-21T00:00:00Z", "late_after_minutes": None}, NOW)

        assert spec.late_after is None

    @pytest.mark.parametrize("body, says", [
        ({"label": " ", "at": "2026-07-21T00:00:00Z"}, "needs a label"),
        ({"label": "x" * 201, "at": "2026-07-21T00:00:00Z"}, "at most 200"),
        ({"label": "x"}, "Say when"),
        ({"label": "x", "at": "2026-07-19T00:00:00Z"}, "already passed"),
        ({"label": "x", "at": "2026-07-21T00:00:00"}, "no offset"),
        ({"label": "x", "repeat": {"every_minutes": 1}}, "every 5 minutes"),
        ({"label": "x", "repeat": {"days": [1], "time": "09:00"}, "at": "2026-07-21T00:00:00Z"},
         "leave out the start"),
        ({"label": "x", "repeat": {"every_minutes": 60}, "until": "2026-07-20T12:30:00Z"},
         "ends before it would first fire"),
        ({"label": "x", "at": "2026-07-21T00:00:00Z", "timezone": "Nowhere/Here"}, "not a time zone"),
        ({"label": "x", "at": "2026-07-21T00:00:00Z", "late_after_minutes": 0}, "whole number of minutes"),
    ])
    def test_refused_with_the_reason(self, body, says):
        with pytest.raises(ReminderError, match=says):
            parse(body, NOW)


def test_how_a_repeat_reads():
    assert describe_repeat(None) is None
    assert describe_repeat({"every_minutes": 30}) == "every 30 minutes"
    assert describe_repeat({"every_minutes": 120}) == "every 2 hours"
    assert describe_repeat({"days": [0, 1, 2, 3, 4], "time": "09:00", "timezone": "UTC"}) == "weekdays at 09:00 (UTC)"


def _timer(**changes):
    base = {"kind": "reminder", "key": "r1", "due_at": 1000.0, "payload": {"label": "Call Ada", "timezone": "UTC"},
            "attempts": 0, "occurrence_at": 1000.0, "owner_user_id": "alice"}
    return Timer(**{**base, **changes})


class TestWhenItFires:
    def test_its_owner_is_reminded(self, tmp_path):
        store = NotificationStore(tmp_path / "n.db")

        fire(store, lambda user: True, Firing(_timer(), 1000.0))

        assert [n.summary for n in store.for_user("alice")] == ["Reminder: Call Ada"]

    def test_delivered_twice_it_is_one_notice(self, tmp_path):
        """A server stopped mid-firing fires it again; the occurrence's
        key makes the second write a no-op."""
        store = NotificationStore(tmp_path / "n.db")

        fire(store, lambda user: True, Firing(_timer(), 1000.0))
        fire(store, lambda user: True, Firing(_timer(due_at=1300.0), 1300.0))

        assert len(store.for_user("alice")) == 1

    def test_the_next_occurrence_is_a_new_notice(self, tmp_path):
        store = NotificationStore(tmp_path / "n.db")

        fire(store, lambda user: True, Firing(_timer(), 1000.0))
        fire(store, lambda user: True, Firing(_timer(due_at=4600.0, occurrence_at=4600.0), 4600.0))

        assert len(store.for_user("alice")) == 2

    def test_missed_says_so_with_how_many_more(self, tmp_path):
        store = NotificationStore(tmp_path / "n.db")

        fire(store, lambda user: True, Firing(_timer(), 9000.0, missed=True, also_missed=2))

        [notice] = store.for_user("alice")
        assert notice.summary.startswith("Missed reminder: Call Ada -- due Thu 01 Jan 00:16 UTC")
        assert notice.summary.endswith("2 later ones were skipped too.")

    def test_back_in_time_for_the_latest_it_delivers_that_and_counts_the_rest(self, tmp_path):
        store = NotificationStore(tmp_path / "n.db")

        fire(store, lambda user: True, Firing(_timer(), 9000.0, also_missed=2, occurrence_at=8200.0))

        [notice] = store.for_user("alice")
        assert notice.summary == ("Reminder: Call Ada. 2 occurrences before this were missed "
                                  "while Elysium was not running.")

    def test_a_disabled_owner_is_not_reminded(self, tmp_path):
        store = NotificationStore(tmp_path / "n.db")

        fire(store, lambda user: False, Firing(_timer(), 1000.0))

        assert store.for_user("alice") == []

    def test_a_notice_that_could_not_be_written_is_retried(self):
        class Broken:
            def notify(self, *args, **kwargs):
                return None

        with pytest.raises(RuntimeError, match="could not write reminder"):
            fire(Broken(), lambda user: True, Firing(_timer(), 1000.0))
