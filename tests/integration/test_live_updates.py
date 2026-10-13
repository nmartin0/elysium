"""Live updates: GET /api/events (api/live_updates.py).

A hint is a TYPE and a VERB, sent only to a caller who may know the type
exists. Read through the real app, the real session and the real
stream.
"""

import json
import threading
import time

import api.live_updates as live_updates


def _login(client, username, role, region="us-west"):
    client.app.state.user_directory.create_user(username, "pw", region, role)
    response = client.post("/api/login", json={"username": username, "password": "pw"})
    assert response.status_code == 204, response.text


def _csrf_headers(client):
    return {"X-CSRF-Token": client.cookies.get("elysium_csrf")}


def _hints_while(client, act, monkeypatch, seconds=1.5):
    """Open the stream, run `act` once the server is listening, and
    return every hint received before the stream ends by itself."""
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
    hints = []
    with client.stream("GET", "/api/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if line.startswith("data: "):
                hints.append(json.loads(line[len("data: "):]))
    return hints


def test_the_stream_needs_a_session(client):
    assert client.get("/api/events").status_code == 401


def test_a_hint_is_a_type_and_a_verb_and_nothing_else(client, monkeypatch):
    _login(client, "seer", "customer_service")
    bus = client.app.state.change_bus

    hints = _hints_while(client, lambda: bus.publish("Customer", "updated"), monkeypatch)

    assert hints == [{"object_type": "Customer", "change": "updated"}]


def test_a_type_the_caller_may_not_know_exists_is_never_mentioned(client, monkeypatch):
    """The accountant reads Account and nothing else. Being told "a
    Customer changed" would tell them this deployment has customers."""
    _login(client, "counter", "accountant")
    bus = client.app.state.change_bus

    def publish_both():
        bus.publish("Customer", "updated")
        bus.publish("Account", "updated")

    hints = _hints_while(client, publish_both, monkeypatch)

    assert hints == [{"object_type": "Account", "change": "updated"}]


def test_the_stream_ends_by_itself_so_the_reconnect_reauthenticates(client, monkeypatch):
    """MAX_STREAM_SECONDS: the caller's visible schema is fixed at
    connect, so a stream that never ended would keep a revoked caller
    hearing type names for as long as the tab stayed open."""
    _login(client, "short", "customer_service")
    started = time.monotonic()

    _hints_while(client, lambda: None, monkeypatch, seconds=0.5)

    assert time.monotonic() - started < 5


def test_an_applied_write_tells_every_listener_which_type_changed(client, monkeypatch):
    """Through the real propose-and-confirm path, not a direct publish."""
    _login(client, "alice", "editor")

    def write():
        proposed = client.post(
            "/api/actions/UpdateCustomerName",
            json={"parameters": {"customer_id": "cust_002", "new_name": "Bram F. Feldman"}},
            headers=_csrf_headers(client))
        write_id = proposed.json()["pending_write"]["id"]
        confirmed = client.post(f"/api/writes/{write_id}/confirm", json={"approved": True},
                                headers=_csrf_headers(client))
        assert confirmed.status_code == 200

    hints = _hints_while(client, write, monkeypatch, seconds=3)

    assert {"object_type": "Customer", "change": "updated"} in hints


def test_a_rejected_write_tells_nobody(client, monkeypatch):
    """THE CONTROL for the one above: nothing changed, so nothing is said."""
    _login(client, "alice2", "editor")

    def reject():
        proposed = client.post(
            "/api/actions/UpdateCustomerName",
            json={"parameters": {"customer_id": "cust_002", "new_name": "Nobody"}},
            headers=_csrf_headers(client))
        write_id = proposed.json()["pending_write"]["id"]
        client.post(f"/api/writes/{write_id}/confirm", json={"approved": False},
                    headers=_csrf_headers(client))

    assert _hints_while(client, reject, monkeypatch, seconds=2) == []


def test_a_new_publication_is_served_without_a_restart(client):
    """FOUND IN A BROWSER: the banner said Customer changed, Refresh was
    clicked, and the old email came back -- the running generation was
    pinned to the previous publication until a restart.
    follow_publications moves it, configuration untouched."""
    import contextlib
    import io
    import sqlite3

    from api.reload import follow_publications
    from scripts.run_sync import run_sync

    _login(client, "reader", "customer_service")
    paths = client.app.state.runtime_paths
    before = client.app.state.generation

    conn = sqlite3.connect(paths.data_dir / "dev_fixtures" / "mediator.db")
    conn.execute("UPDATE customers SET email = 'bram.new@example.com' WHERE customer_id = 'cust_002'")
    conn.commit()
    conn.close()
    with contextlib.redirect_stdout(io.StringIO()):
        run_sync(paths)

    stale = client.get("/api/objects/Customer/cust_002").json()["fields"]["email"]
    follow_publications(client.app)
    fresh = client.get("/api/objects/Customer/cust_002").json()["fields"]["email"]

    assert stale != "bram.new@example.com", "the control: pinned until followed"
    assert fresh == "bram.new@example.com"
    assert client.app.state.generation.source_digest == before.source_digest


def test_following_a_publication_never_applies_an_unreloaded_edit(client, monkeypatch):
    """It builds from the bytes the RUNNING generation was built from,
    not from whatever is on disk now."""
    import api.reload as reload

    seen = {}

    def capture(config_dir, *_args, **_kwargs):
        seen.update({path.name: path.read_text() for path in config_dir.iterdir()})
        raise RuntimeError("stop here")

    monkeypatch.setattr(reload, "build_generation", capture)
    running = client.app.state.generation.config.source_text

    assert reload.follow_publications(client.app) is None
    assert {name: seen[name] for name in running} == dict(running)
