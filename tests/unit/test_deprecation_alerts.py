"""Alerts on `remove_after` (core/ontology/deprecation_alerts.py): who is
told, when, once, and that nothing is removed."""

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from api.deprecation_alerts import KIND, arm, deprecation_timer
from api.timer_service import Firing
from core.notifications import NotificationStore
from core.ontology.deprecation_alerts import (
    DEFAULT_LEAD_DAYS,
    LEAD,
    OVERDUE,
    PROBLEM,
    findings,
    lead_days_from,
    send,
    words,
)
from core.timers import Timer, TimerStore
from core.user_directory import UserDirectory

TODAY = date(2027, 3, 1)


def _schema(**blocks):
    """A type, a stored field and a link, each deprecated with the date in `blocks`."""
    def deprecated(name):
        when = blocks.get(name)
        return {"status": "deprecated", "deprecation": {"reason": "old", "remove_after": when}} \
            if name in blocks else {}
    return {"Customer": {**deprecated("type"), "fields": {
        "email": {"type": "string", **deprecated("field")},
        "tags": {"type": "link", "link_type": "CustomerTags", **deprecated("link")}}},
        "Tag": {"fields": {"customers": {"type": "link", "link_type": "CustomerTags", **deprecated("link")}}}}


class TestWhichStage:
    @pytest.mark.parametrize("when,stage,days", [
        (date(2027, 3, 31), LEAD, 30), (date(2027, 3, 2), LEAD, 1),
        (date(2027, 3, 1), OVERDUE, 0), (date(2027, 2, 20), OVERDUE, 9)])
    def test_the_stage_from_the_date(self, when, stage, days):
        [found] = findings(_schema(field=when), TODAY, 30)

        assert (found.stage, found.days, found.kind, found.name) == (stage, days, "field", "Customer.email")

    def test_beyond_the_lead_window_says_nothing(self):
        assert findings(_schema(field=date(2027, 4, 1)), TODAY, 30) == []

    def test_the_window_is_the_config_value(self):
        assert findings(_schema(field=date(2027, 3, 10)), TODAY, 5) == []
        assert len(findings(_schema(field=date(2027, 3, 10)), TODAY, 9)) == 1

    def test_no_date_no_finding(self):
        assert findings(_schema(field=None), TODAY, 30) == []

    def test_types_fields_and_a_link_once_each(self):
        found = findings(_schema(type=date(2027, 3, 5), field=date(2027, 3, 5), link=date(2027, 3, 5)), TODAY, 30)

        assert sorted((f.kind, f.name) for f in found) == [
            ("field", "Customer.email"), ("link type", "CustomerTags"), ("type", "Customer")]

    def test_quoted_text_dates_are_read(self):
        assert findings(_schema(field="2027-03-05"), TODAY, 30)[0].stage == LEAD

    @pytest.mark.parametrize("bad", ["soon", "2027-13-45", 20270305, "", datetime(2027, 3, 5)])
    def test_a_date_that_is_not_one_is_a_problem_not_silence_or_a_crash(self, bad):
        [found] = findings(_schema(field=bad), TODAY, 30)

        assert found.stage == PROBLEM
        summary, detail = words(found, None)
        assert "not a date" in summary and repr(bad) in detail


class TestLeadWindowSetting:
    def test_absent_is_the_default(self):
        assert lead_days_from(None) == DEFAULT_LEAD_DAYS == 30

    @pytest.mark.parametrize("bad", [-1, 366, "30", 2.5, True])
    def test_refused_with_the_reason(self, bad):
        with pytest.raises(ValueError, match="deprecation_lead_days"):
            lead_days_from(bad)


class TestTheNotice:
    def test_it_says_what_when_how_used_and_where(self):
        [found] = findings(_schema(field=date(2027, 3, 11)), TODAY, 30)

        summary, detail = words(found, 3)

        assert "field Customer.email" in summary and "2027-03-11" in summary and "10 days" in summary
        assert "3 places in the configuration" in detail and "not counted" in detail
        assert "Schema" in detail and "Nothing is removed automatically" in detail

    def test_it_does_not_invent_a_count(self):
        [found] = findings(_schema(field=date(2027, 3, 11)), TODAY, 30)

        assert "could not be worked out" in words(found, None)[1]

    def test_overdue_says_it_is_still_there(self):
        [found] = findings(_schema(type=date(2027, 2, 27)), TODAY, 30)

        summary, detail = words(found, 0)
        assert "still there" in summary and "passed 2 days ago" in detail and "can be removed" in detail


class TestOncePerItemPerStagePerPerson:
    def test_a_repeat_is_one_notice(self, tmp_path):
        store = NotificationStore(tmp_path / "n.db")
        found = findings(_schema(field=date(2027, 3, 11)), TODAY, 30)

        for _ in range(3):
            send(found, ["ann", "bob"], store, lambda _f: 1)

        assert [len(store.for_user(u)) for u in ("ann", "bob")] == [1, 1]

    def test_the_next_stage_is_a_second_notice_and_a_moved_date_a_new_one(self, tmp_path):
        store = NotificationStore(tmp_path / "n.db")
        send(findings(_schema(field=date(2027, 3, 11)), TODAY, 30), ["ann"], store, lambda _f: 1)
        send(findings(_schema(field=date(2027, 3, 11)), date(2027, 3, 12), 30), ["ann"], store, lambda _f: 1)
        send(findings(_schema(field=date(2027, 3, 11)), date(2027, 3, 13), 30), ["ann"], store, lambda _f: 1)
        send(findings(_schema(field=date(2027, 9, 1)), date(2027, 8, 20), 30), ["ann"], store, lambda _f: 1)

        assert len(store.for_user("ann")) == 3


def _app(tmp_path, schema, lead=30):
    roles = {"ops": {"allowed_actions": frozenset({"manage:deployment"})}, "plain": {"allowed_actions": frozenset()}}
    directory = UserDirectory(tmp_path / "credentials.db", roles)
    for name, role in (("ann", "ops"), ("bob", "ops"), ("cyd", "plain"), ("dee", "ops")):
        directory.create_user(name, "pw-long-enough-1", None, role)
    directory.disable_user("dee")
    config = SimpleNamespace(schema=schema, roles=roles, action_types={}, declared_triggers=(),
                             deprecation_lead_days=lead)
    return SimpleNamespace(state=SimpleNamespace(
        runtime_paths=SimpleNamespace(data_dir=tmp_path), generation=SimpleNamespace(config=config)))


def _firing(day):
    at = datetime(day.year, day.month, day.day, 6, tzinfo=UTC).timestamp()
    return Firing(Timer(KIND, "daily", at, {}, 0, occurrence_at=at), at)


class TestWhoIsToldAndWhere:
    def test_only_active_holders_of_manage_deployment(self, tmp_path):
        app = _app(tmp_path, _schema(field=date(2027, 3, 11)))

        deprecation_timer(app, _firing(TODAY))
        deprecation_timer(app, _firing(TODAY))

        store = NotificationStore(tmp_path / "notifications.db")
        assert [len(store.for_user(u)) for u in ("ann", "bob", "cyd", "dee")] == [1, 1, 0, 0]
        [notice] = store.for_user("ann")
        assert notice.kind == "deprecation" and "Customer.email" in notice.summary

    def test_a_bad_date_is_a_visible_notice_and_the_good_ones_still_go(self, tmp_path):
        app = _app(tmp_path, _schema(field="soon", type=date(2027, 3, 11)))

        deprecation_timer(app, _firing(TODAY))

        summaries = [n.summary for n in NotificationStore(tmp_path / "notifications.db").for_user("ann")]
        assert len(summaries) == 2 and any("not a date" in s for s in summaries)

    def test_the_count_comes_from_the_used_by_report(self, tmp_path):
        schema = _schema(field=date(2027, 3, 11))
        app = _app(tmp_path, schema)
        app.state.generation.config.roles["ops"]["allowed_actions"] = frozenset(
            {"manage:deployment", "read:Customer.email"})

        deprecation_timer(app, _firing(TODAY))

        [notice] = NotificationStore(tmp_path / "notifications.db").for_user("ann")
        assert "1 place in the configuration still name it" in notice.detail

    def test_nothing_in_the_schema_is_touched(self, tmp_path):
        schema = _schema(type=date(2020, 1, 1))
        before = repr(schema)

        deprecation_timer(_app(tmp_path, schema), _firing(TODAY))

        assert repr(schema) == before

    def test_nobody_to_tell_is_not_a_crash(self, tmp_path):
        app = _app(tmp_path, _schema(field=date(2027, 3, 11)))
        app.state.generation.config.roles["ops"]["allowed_actions"] = frozenset()

        deprecation_timer(app, _firing(TODAY))

        assert NotificationStore(tmp_path / "notifications.db").for_user("ann") == []


class TestArming:
    def test_set_once_daily_and_not_moved_by_a_restart(self, tmp_path):
        app = _app(tmp_path, {})

        arm(app)
        first = TimerStore(tmp_path).get(KIND, "daily")
        arm(app)

        assert first.repeat == {"every_minutes": 1440}
        assert TimerStore(tmp_path).get(KIND, "daily").due_at == first.due_at


def test_the_app_runs_the_check_on_the_timer_service_it_already_has():
    """No thread of its own: the handler is registered with the one timer
    service, and the daily timer is armed where the others are."""
    from pathlib import Path

    source = Path("api/app.py").read_text()

    assert "DEPRECATION_DATES: deprecation_timer," in source
    assert "arm_deprecation_dates(_app)" in source


class TestTheSettingReachesTheLoadedConfiguration:
    def _load(self, tmp_path, value):
        import shutil

        from core.deployment_loader import load_deployment

        config_dir = tmp_path / "config"
        shutil.copytree("tests/integration/fixtures", config_dir)
        if value is not None:
            with open(config_dir / "config.yaml", "a") as config:
                config.write(f"\ndeprecation_lead_days: {value}\n")
        return load_deployment(config_dir)

    def test_absent_is_thirty(self, tmp_path):
        assert self._load(tmp_path, None).deprecation_lead_days == 30

    def test_a_declared_value_is_carried(self, tmp_path):
        assert self._load(tmp_path, 14).deprecation_lead_days == 14

    def test_a_bad_value_is_refused_at_load(self, tmp_path):
        with pytest.raises(ValueError, match="deprecation_lead_days"):
            self._load(tmp_path, -3)
