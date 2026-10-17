"""Reminders through the real routes (17 October): made, listed and
cancelled by their owner alone, and fired by the timer service into the
owner's notifications."""

from datetime import UTC, datetime, timedelta

from api.reminders import reminder_timer
from api.timer_service import fire_due
from core.reminders import KIND, MAX_PER_PERSON
from tests.integration.test_trigger_checks import _csrf, _login


def _make(client, **body):
    return client.post("/api/reminders", json={"label": "Call Ada", **body}, headers=_csrf(client))


def _in(minutes):
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def test_made_listed_and_cancelled_by_its_owner(client):
    _login(client, "alice")
    made = _make(client, at=_in(30))
    assert made.status_code == 200, made.text
    reminder_id = made.json()["reminder_id"]

    assert [r["label"] for r in client.get("/api/reminders").json()["reminders"]] == ["Call Ada"]

    assert client.delete(f"/api/reminders/{reminder_id}", headers=_csrf(client)).status_code == 200
    assert client.get("/api/reminders").json()["reminders"] == []


def test_nobody_else_sees_or_cancels_it(client):
    """The same 404 as for one that does not exist."""
    _login(client, "alice")
    reminder_id = _make(client, at=_in(30)).json()["reminder_id"]
    _login(client, "bob")

    assert client.get("/api/reminders").json()["reminders"] == []
    assert client.delete(f"/api/reminders/{reminder_id}", headers=_csrf(client)).status_code == 404
    assert client.delete("/api/reminders/no-such-one", headers=_csrf(client)).status_code == 404


def test_a_repeat_reads_as_it_was_asked_for(client):
    _login(client, "alice")

    made = _make(client, repeat={"days": [0, 1, 2, 3, 4], "time": "09:00"}, timezone="Europe/London").json()

    assert made["repeats"] == "weekdays at 09:00 (Europe/London)"


def test_refused_with_the_reason(client):
    _login(client, "alice")

    response = _make(client, at="2020-01-01T00:00:00Z")

    assert response.status_code == 400
    assert "already passed" in response.json()["detail"]


def test_one_person_may_have_so_many(client, monkeypatch):
    import core.reminders
    monkeypatch.setattr(core.reminders, "MAX_PER_PERSON", 2)
    _login(client, "alice")
    _make(client, at=_in(30))
    _make(client, at=_in(31))

    response = _make(client, at=_in(32))

    assert response.status_code == 400
    assert "the most one person may have" in response.json()["detail"]
    assert MAX_PER_PERSON == 100


def test_when_it_comes_due_its_owner_is_notified(client):
    """End to end: the route stores it, the timer service fires it, the
    handler the server registers writes the notice."""
    _login(client, "alice")
    _make(client, at=_in(30))
    due = datetime.now(UTC) + timedelta(minutes=30, seconds=1)

    ran = fire_due(client.app, {KIND: reminder_timer}, clock=lambda: due.timestamp())

    assert ran == 1
    summaries = [n["summary"] for n in client.get("/api/notifications").json()["notifications"]]
    assert summaries == ["Reminder: Call Ada"]
    assert client.get("/api/reminders").json()["reminders"] == []
