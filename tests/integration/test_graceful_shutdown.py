"""
A shutdown that lands mid-confirm lets the confirm finish -- the write
applied and BOTH its audit entries written (E-12).

Patch 305 configured it: uvicorn waits 30 s for in-flight requests,
systemd 45 s. Nothing tested it. This runs the app under a REAL uvicorn
server, slows the write so the shutdown lands after the "pre" audit
entry and before the "post", asks the server to exit exactly as SIGTERM
does, and checks everything completed.
"""

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from core.ontology.write_mediator import WriteMediator

# What install/elysium.service passes: --timeout-graceful-shutdown 30.
GRACE_SECONDS = 30
# How long the CLIENT waits -- systemd's TimeoutStopSec, and kept apart
# from GRACE_SECONDS: tied to it, a short grace made the client time out
# by itself, and the control proved nothing about the server.
CLIENT_WAITS = 45
WRITE_TAKES = 1.5


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _post(url, body, headers=None, timeout=10):
    """POST JSON with the standard library -- no HTTP client is in the
    lock file, and CI installs only what is locked."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


def _audit(app):
    path = app.state.generation.mediator.audit_log._log_path
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_a_confirm_in_flight_at_shutdown_completes(client, monkeypatch):
    app = client.app
    app.state.user_directory.create_user("alice", "a-long-and-unremarkable-passphrase", "us-west", "editor")

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                                           timeout_graceful_shutdown=GRACE_SECONDS))
    serving = threading.Thread(target=server.run, daemon=True)
    serving.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started

    base = f"http://127.0.0.1:{port}"
    status, login_headers, _ = _post(f"{base}/api/login",
                                     {"username": "alice", "password": "a-long-and-unremarkable-passphrase"})
    assert status == 204
    # The session cookie is Secure, so a client over plain http will not
    # send it by itself; it is sent by hand.
    cookies = dict(c.split(";", 1)[0].split("=", 1) for c in login_headers.get_all("Set-Cookie"))
    headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
               "X-CSRF-Token": cookies["elysium_csrf"]}
    _, _, proposed = _post(f"{base}/api/actions/UpdateCustomerName",
                           {"parameters": {"customer_id": "cust_002", "new_name": "Bram F. Feldman"}}, headers)
    write_id = json.loads(proposed)["pending_write"]["id"]

    # SLOW THE WRITE, between the "pre" audit entry and the "post".
    applying = threading.Event()
    real_apply = WriteMediator._apply_one_update

    def slow_apply(self, *args, **kwargs):
        applying.set()
        time.sleep(WRITE_TAKES)
        return real_apply(self, *args, **kwargs)
    monkeypatch.setattr(WriteMediator, "_apply_one_update", slow_apply)

    outcome = {}

    def confirm():
        try:
            outcome["status"], _, _ = _post(f"{base}/api/writes/{write_id}/confirm",
                                            {"approved": True}, headers, timeout=CLIENT_WAITS)
        except OSError as exc:  # the connection cut before a response
            outcome["error"] = repr(exc)
        outcome["finished_at"] = time.monotonic()
    confirming = threading.Thread(target=confirm)
    confirming.start()

    assert applying.wait(10), "the write never started"
    exit_requested_at = time.monotonic()
    server.should_exit = True  # what uvicorn's SIGTERM handler does
    confirming.join(CLIENT_WAITS)
    serving.join(CLIENT_WAITS)

    # THE SHUTDOWN LANDED MID-WRITE: the confirm finished after it.
    assert outcome.get("finished_at", 0) > exit_requested_at
    assert not serving.is_alive(), "the server did not shut down"
    # AND THE CONFIRM COMPLETED.
    assert outcome.get("status") == 200, outcome
    # THE WRITE WAS APPLIED.
    client.post("/api/login", json={"username": "alice", "password": "a-long-and-unremarkable-passphrase"})
    assert client.get("/api/objects/Customer/cust_002").json()["fields"]["name"] == "Bram F. Feldman"
    # AND BOTH AUDIT ENTRIES WERE WRITTEN, paired by request id.
    entries = _audit(app)
    pre = [e for e in entries if e.get("stage") == "pre" and e.get("action_id") == "write:UpdateCustomerName"]
    assert len(pre) == 1
    post = [e for e in entries if e.get("stage") == "post" and e.get("request_id") == pre[0]["request_id"]]
    assert [e["status"] for e in post] == ["success"]
