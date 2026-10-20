"""A trigger warning when a total per period is projected to cross a line
(R68, core/projected_condition.py): when it is told, once, as each
person, and not on a forecast that is not trusted."""

import datetime

import numpy as np
import pytest

from core.notifications import NotificationStore
from core.projected_condition import KIND, WATCHING, evaluate_projected, problem
from core.saved_views import SavedView
from core.triggers import Trigger, describe

TODAY = datetime.date(2026, 10, 14)        # a Wednesday
THIS_WEEK = datetime.date(2026, 10, 12)
SCHEMA = {"Refund": {"id_field": "refund_id", "fields": {
    "refund_id": {"type": "data"}, "requested": {"type": "data", "data_type": "date"},
    "reason": {"type": "data"}}}}
VIEW = SavedView("v1", "Refunds", "Refund", "", [], {}, "2026-01-01")


def _trigger(above=50.0, roles=()):
    return Trigger("t1", "alice", "Refunds", "v1", None, None, None, True, "2026-01-01",
                   recipient_roles=roles, projected_field="requested",
                   projected_period="week", projected_above=above)


class Person:
    def __init__(self, user_id, role="analyst"):
        self.user_id = user_id
        self.role_name = role


class Totals:
    """A mediator's aggregate, per person: their own weekly totals."""

    schema = SCHEMA

    def __init__(self, series_by_user):
        self.series_by_user = series_by_user
        self.asked = []

    def aggregate_by_field(self, user, object_type, conditions, *, group_by, aggregate, outcome,
                           query_text, period):
        self.asked.append((user.user_id, object_type, group_by, aggregate, period))
        values = self.series_by_user[user.user_id]
        starts = [THIS_WEEK - datetime.timedelta(weeks=len(values) - 1 - index)
                  for index in range(len(values))]
        return dict(zip(starts, values, strict=True))


def _rising(last_finished, weeks=40, seed=0):
    """Weekly counts climbing steadily to `last_finished`, then a running
    week partly counted."""
    rng = np.random.default_rng(seed)
    climb = np.linspace(last_finished - 0.5 * weeks, last_finished, weeks)
    return [*np.round(climb + rng.normal(0, 1, weeks)), 3.0]


@pytest.fixture
def store(tmp_path):
    return NotificationStore(tmp_path / "notifications.db")


def _said(store, user_id, kind=None):
    return [note.summary for note in store.for_user(user_id)
            if kind is None or note.kind == kind]


class TestWhenItIsTold:
    def test_first_it_is_watching_then_told_once_on_becoming_projected(self, store):
        people = {"alice": Person("alice")}
        mediator = Totals({"alice": _rising(30)})
        assert evaluate_projected(_trigger(), VIEW, mediator, store, people, "d", TODAY) == 0
        (watching,) = _said(store, "alice", WATCHING)
        assert watching.startswith("Refunds per week projected above 50: now watching, "
                                   "currently projected at most")

        mediator.series_by_user["alice"] = _rising(60)
        assert evaluate_projected(_trigger(), VIEW, mediator, store, people, "d", TODAY) == 1
        (told,) = _said(store, "alice", KIND)
        assert told.startswith("Refunds per week projected above 50: forecast ")
        assert "for the week of 12 Oct 2026" in told and "80% range" in told

        # STILL PROJECTED: not told again.
        assert evaluate_projected(_trigger(), VIEW, mediator, store, people, "d", TODAY) == 0
        # BACK UNDER, then over again: told again.
        mediator.series_by_user["alice"] = _rising(30)
        evaluate_projected(_trigger(), VIEW, mediator, store, people, "d", TODAY)
        mediator.series_by_user["alice"] = _rising(61, seed=1)
        assert evaluate_projected(_trigger(), VIEW, mediator, store, people, "d", TODAY) == 1
        assert len(_said(store, "alice", KIND)) == 2

    def test_already_past_the_line_when_made_is_said_in_the_watching_notice(self, store):
        evaluate_projected(_trigger(), VIEW, Totals({"alice": _rising(70)}), store,
                           {"alice": Person("alice")}, "d", TODAY)
        assert _said(store, "alice", WATCHING) == [
            "Refunds per week projected above 50: now watching, currently projected to pass it."]

    def test_a_forecast_not_trusted_neither_fires_nor_clears(self, store):
        people = {"alice": Person("alice")}
        mediator = Totals({"alice": [5.0, 6.0, 3.0]})    # three weeks: too little
        evaluate_projected(_trigger(), VIEW, mediator, store, people, "d", TODAY)
        (watching,) = _said(store, "alice", WATCHING)
        # Three weeks: one running, one the records began part-way through,
        # one whole one to forecast from.
        assert "No projection yet: Only 1 whole week of records" in watching
        assert evaluate_projected(_trigger(), VIEW, mediator, store, people, "d", TODAY) == 0
        assert len(_said(store, "alice")) == 1

    def test_a_changed_configuration_is_a_new_baseline(self, store):
        people = {"alice": Person("alice")}
        mediator = Totals({"alice": _rising(30)})
        evaluate_projected(_trigger(), VIEW, mediator, store, people, "before", TODAY)
        mediator.series_by_user["alice"] = _rising(60)
        assert evaluate_projected(_trigger(), VIEW, mediator, store, people, "after", TODAY) == 0


class TestWhatItReads:
    def test_the_forecast_line_not_the_top_of_its_range(self, monkeypatch):
        import core.forecasts
        from core.forecasts import Forecast
        from core.projected_condition import projection_for

        made = Forecast([{"start": "2026-10-12", "value": 45.0, "low": 38.0, "high": 55.0}],
                        None, {"share": 0.1})
        monkeypatch.setattr(core.forecasts, "cached_forecast", lambda *a, **k: made)
        projection = projection_for(Totals({"alice": _rising(30)}), VIEW, _trigger(50.0),
                                    Person("alice"), TODAY)
        assert projection["state"] == "clear", "the range passes 50; the forecast does not"
        made.points[0]["value"] = 51.0
        assert projection_for(Totals({"alice": _rising(30)}), VIEW, _trigger(50.0),
                              Person("alice"), TODAY)["state"] == "projected"

    def test_a_cut_off_set_is_not_trusted(self):
        from core.projected_condition import projection_for

        class CutOff(Totals):
            def aggregate_by_field(self, user, *args, outcome, **kwargs):
                outcome.scan_truncated = True
                return super().aggregate_by_field(user, *args, outcome=outcome, **kwargs)

        projection = projection_for(CutOff({"alice": _rising(60)}), VIEW, _trigger(),
                                    Person("alice"), TODAY)
        assert projection["state"] == "untrusted" and "only part of the set" in projection["reason"]


class TestAsEachPerson:
    def test_each_recipient_is_projected_from_their_own_totals(self, store):
        people = {"alice": Person("alice"), "bob": Person("bob", "support")}
        mediator = Totals({"alice": _rising(30), "bob": _rising(30)})
        trigger = _trigger(roles=("support",))
        evaluate_projected(trigger, VIEW, mediator, store, people, "d", TODAY)
        mediator.series_by_user["bob"] = _rising(60)
        assert evaluate_projected(trigger, VIEW, mediator, store, people, "d", TODAY) == 1
        assert _said(store, "bob", KIND) and not _said(store, "alice", KIND)
        assert {asked[0] for asked in mediator.asked} == {"alice", "bob"}
        assert set(asked[1:] for asked in mediator.asked) == {
            ("Refund", "requested", "count", "week")}

    def test_an_owner_who_is_gone_runs_for_nobody(self, store):
        assert evaluate_projected(_trigger(), VIEW, Totals({}), store, {}, "d", TODAY) == 0


class TestTheDeclaration:
    def test_it_reads_as_a_sentence(self):
        assert describe(_trigger()) == "Refunds per week projected above 50"

    @pytest.mark.parametrize("field, period, above, others, why", [
        ("requested", None, 50, {}, "needs a date field, a period and a line"),
        ("requested", "fortnight", 50, {}, "The period is one of"),
        ("reason", "week", 50, {}, "not a date field"),
        ("requested", "week", 0, {}, "a number above 0"),
        ("requested", "week", 50, {"above": 3}, "stands alone.*above"),
        ("requested", "week", 50, {"an action": "Escalate"}, "stands alone.*an action"),
    ])
    def test_one_that_could_not_be_checked_is_refused(self, field, period, above, others, why):
        with pytest.raises(AssertionError, match=why):
            refused = problem("Refund", SCHEMA, field, period, above, others=others)
            assert refused is None, refused

    def test_a_good_one_is_not(self):
        assert problem("Refund", SCHEMA, "requested", "week", 50, others={"above": None}) is None
