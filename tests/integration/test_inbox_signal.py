"""'Your inbox changed', on the live-updates stream (16 October).

A notification written in the server reaches its recipient's open tabs
at once: an `inbox` event, to them and nobody else, carrying nothing.
Through the real app, session and stream, as test_live_updates.py.
"""

import threading
import time

import api.live_updates as live_updates
from core.notifications import NotificationStore, on_notify


def _login(client, username):
    client.app.state.user_directory.create_user(username, "pw", "us-west", "customer_service")
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _events_while(client, act, monkeypatch, seconds=1.5):
    """Every event name and data line received, while `act` runs once
    the stream is listening."""
    monkeypatch.setattr(live_updates, "MAX_STREAM_SECONDS", seconds)
    monkeypatch.setattr(live_updates, "HEARTBEAT_SECONDS", 0.2)
    bus = client.app.state.change_bus

    def when_listening():
        for _ in range(200):
            if bus.listening:
                act()
                return
            time.sleep(0.01)

    threading.Thread(target=when_listening, daemon=True).start()
    lines = []
    with client.stream("GET", "/api/events") as response:
        for line in response.iter_lines():
            if line.startswith(("event: ", "data: ")):
                lines.append(line)
    return lines


def test_a_person_is_told_their_own_inbox_changed(client, monkeypatch):
    _login(client, "alice")
    bus = client.app.state.change_bus

    lines = _events_while(client, lambda: bus.publish_inbox("alice"), monkeypatch)

    assert lines == ["event: inbox", "data: {}"]


def test_nobody_else_is(client, monkeypatch):
    """Being told someone else's inbox changed would say when they get
    alerts -- the same rule as never naming a type the caller may not
    know exists."""
    _login(client, "alice")
    bus = client.app.state.change_bus

    lines = _events_while(client, lambda: bus.publish_inbox("bob"), monkeypatch)

    assert lines == []


def test_writing_a_notification_announces_the_recipient_only(tmp_path):
    heard = []
    remove = on_notify(heard.append)
    try:
        NotificationStore(tmp_path / "n.db").notify("alice", "trigger", "Something crossed")
    finally:
        remove()

    assert heard == ["alice"]


def test_writing_one_reaches_the_stream_end_to_end(client, monkeypatch):
    """What the server wires at start (api/app.py): a notification
    written in this process becomes an `inbox` event for its owner."""
    _login(client, "alice")
    bus = client.app.state.change_bus
    remove = on_notify(bus.publish_inbox)
    store = NotificationStore(client.app.state.runtime_paths.data_dir / "notifications.db")
    try:
        lines = _events_while(client, lambda: store.notify("alice", "trigger", "x"), monkeypatch)
    finally:
        remove()

    assert lines == ["event: inbox", "data: {}"]
