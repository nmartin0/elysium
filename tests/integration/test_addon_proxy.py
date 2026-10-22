"""The proxy to an add-on's own server (BLOCKING.md item 3, step 2.1):
/api/addons/{id}/... reaches the server named in the add-on's state file,
saying who is asking with a signed token, and passing nothing of the
session either way (core/addons.py, api/addon_servers.py).

THE SERVER HERE IS STARTED BY THE TEST, in a thread, and its state file
written by hand: this is the proxy's half of the meeting point. The
supervisor's half -- starting it, and writing the file -- has its own
tests (test_addon_lifecycle.py)."""

import json
import socket
import sys
import threading
from pathlib import Path

import pytest

import api.addon_servers as addon_servers
from api.addon_servers import STATE_FILENAME, addon_directory
from tests.integration.test_api import _csrf_headers, _login
from tests.integration.test_editing_config_from_the_ui import config_dir  # noqa: F401

ECHO = Path(__file__).resolve().parents[1] / "addons" / "echo"
sys.path.insert(0, str(ECHO))
from server import make_server  # noqa: E402 -- the example add-on's own server

SHIPPED = ["ui/packages/app-browse", "ui/packages/app-query", "ui/packages/app-schema", "ui/src/inbox",
           "ui/packages/app-approvals", "ui/packages/app-notifications", "ui/packages/app-identity",
           "ui/packages/app-admin"]


def write_modules(directory: Path, *extra: Path) -> None:
    lines = ["home: /query", "modules:", *[f"  - {m}" for m in SHIPPED], *[f"  - {e}" for e in extra]]
    (directory / "modules.yaml").write_text("\n".join(lines) + "\n")


def guarded_module(tmp_path: Path) -> Path:
    """An add-on offered only to manage:deployment."""
    folder = tmp_path / "guarded"
    folder.mkdir()
    (folder / "module.json").write_text(json.dumps({
        "id": "guarded", "name": "Guarded", "version": "1", "permission": "manage:deployment",
        "server": {"command": ["{python}", str(ECHO / "server.py")]}}))
    return folder


def write_state(data_dir: Path, module_id: str, **state) -> None:
    directory = addon_directory(data_dir, module_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / STATE_FILENAME).write_text(json.dumps(state))


def serve(data_dir: Path, module_id: str, options: "dict | None" = None):
    secret = f"secret-of-{module_id}"
    info = {"contract": 1, "id": module_id, "options": options or {},
            "identity": {"header": "X-Elysium-Identity", "secret": secret,
                         "issuer": "elysium", "audience": module_id}}
    server = make_server(info)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    write_state(data_dir, module_id, state="running", secret=secret,
                url=f"http://127.0.0.1:{server.server_address[1]}")
    return server


@pytest.fixture
def alice(config_dir, tmp_path, request):  # noqa: F811
    write_modules(config_dir, ECHO, guarded_module(tmp_path))
    client = request.getfixturevalue("client")
    data_dir = client.app.state.runtime_paths.data_dir
    servers = [serve(data_dir, "echo"), serve(data_dir, "guarded")]
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    _login(client, "alice", "correct-pw")
    yield client
    for server in servers:
        server.shutdown()


def test_the_add_on_is_told_who_is_asking_and_nothing_of_the_session(alice):
    response = alice.get("/api/addons/echo/whoami", headers={"X-Elysium-Identity": "forged",
                                                             "Authorization": "Bearer x"})

    assert response.status_code == 200, response.text
    seen = response.json()
    assert seen["user"] == "alice" and seen["claims"]["aud"] == "echo"
    assert "cookie" not in seen["headers"] and "authorization" not in seen["headers"]
    assert "x-elysium-identity" in seen["headers"]


def test_a_write_carries_its_body_and_needs_the_csrf_token_like_any(alice):
    refused = alice.post("/api/addons/echo/whoami", json={"speed": 60})
    assert refused.status_code == 403

    response = alice.post("/api/addons/echo/whoami", json={"speed": 60}, headers=_csrf_headers(alice))

    assert response.status_code == 200, response.text
    seen = response.json()
    assert seen["method"] == "POST" and json.loads(seen["body"]) == {"speed": 60}
    assert "x-csrf-token" not in seen["headers"]


def test_the_path_arrives_as_sent_encoded_slash_and_query_included(alice):
    seen = alice.get("/api/addons/echo/whoami/a%2Fb?pack=retail&x=1").json()

    assert seen["path"] == "/whoami/a%2Fb" and seen["query"] == "pack=retail&x=1"


def test_no_cookie_and_no_loopback_address_come_back_and_what_does_is_sandboxed(alice):
    response = alice.get("/api/addons/echo/cookie", follow_redirects=False)

    assert response.status_code == 200
    assert "set-cookie" not in response.headers and "location" not in response.headers
    assert response.headers["etag"] == '"e1"'
    assert response.headers["content-security-policy"].startswith("sandbox")
    # Private unless the add-on says otherwise.
    assert response.headers["cache-control"] == "no-store"


def test_an_event_stream_arrives_as_events(alice):
    with alice.stream("GET", "/api/addons/echo/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        text = "".join(response.iter_text())

    assert [line for line in text.splitlines() if line] == ["data: 0", "data: 1", "data: 2"]


def test_streams_beyond_the_limit_are_a_503_and_ordinary_requests_still_pass(alice, monkeypatch):
    monkeypatch.setattr(addon_servers, "_streams", threading.BoundedSemaphore(1))
    addon_servers._streams.acquire()

    assert alice.get("/api/addons/echo/events").status_code == 503
    assert alice.get("/api/addons/echo/whoami").status_code == 200


@pytest.mark.parametrize("address", [
    "/api/addons/guarded/whoami",   # an add-on this person is not offered
    "/api/addons/browse/whoami",    # a module with no server
    "/api/addons/nothing/whoami",   # no such module
])
def test_what_this_person_may_not_reach_is_a_404_alike(alice, address):
    response = alice.get(address)

    assert response.status_code == 404 and response.json() == {"detail": "Not found"}


def test_nobody_signed_in_reaches_nothing(alice):
    alice.cookies.clear()

    assert alice.get("/api/addons/echo/whoami").status_code == 401


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.mark.parametrize("state", [
    None,
    {"state": "starting", "url": "http://127.0.0.1:9", "secret": "x"},
    {"state": "running", "url": f"http://127.0.0.1:{_closed_port()}", "secret": "x"},
])
def test_a_server_not_running_is_a_503_saying_so(alice, state):
    data_dir = alice.app.state.runtime_paths.data_dir
    path = addon_directory(data_dir, "echo") / STATE_FILENAME
    if state is None:
        path.unlink()
    else:
        path.write_text(json.dumps(state))

    response = alice.get("/api/addons/echo/whoami")

    assert response.status_code == 503
    assert "server" in response.json()["detail"]
