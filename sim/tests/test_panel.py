"""The control panel's server (sim/panel/server.py), against the HTTP it
answers: who may ask, what it says of a world in each phase, what it
refuses, and -- with real databases, as an ordinary user -- a world it
starts carrying on while the panel is gone, and found again after.

The token Elysium's proxy would add is made here with the standard
library: the simulator imports nothing of Elysium's, its tests included.
"""

import base64
import fcntl
import hashlib
import hmac
import importlib.util
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

PANEL = Path(__file__).resolve().parents[1] / "panel"
SECRET = "panel-test-secret-panel-test-secret"


def _load_panel():
    spec = importlib.util.spec_from_file_location("simulator_panel_server", PANEL / "server.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


panel_server = _load_panel()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token(user="ada", permissions=("module:simulator:operate",), audience="simulator") -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"iss": "elysium", "aud": audience, "sub": user, "iat": now,
                            "exp": now + 60, "permissions": list(permissions)}).encode())
    signature = hmac.new(SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def info(directory: Path, outbox: "Path | None" = None) -> dict:
    return {"contract": 1, "id": "simulator", "options": {"directory": str(directory)},
            "dataDir": str(directory.parent / "data"),
            **({} if outbox is None else {"outbox": str(outbox)}),
            "identity": {"header": "X-Elysium-Identity", "secret": SECRET, "issuer": "elysium",
                         "audience": "simulator"}}


class Client:
    def __init__(self, port: int) -> None:
        self.port = port

    def __call__(self, method: str, path: str, body=None, **who):
        headers = {"Content-Type": "application/json"}
        if who.get("signed", True):
            headers["X-Elysium-Identity"] = token(**{k: v for k, v in who.items() if k != "signed"})
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method, headers=headers,
            data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())


@pytest.fixture
def panel(tmp_path):
    server = panel_server.make_server(info(tmp_path / "world"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield Client(server.server_address[1]), tmp_path / "world"
    server.shutdown()


# -- who may ask --------------------------------------------------------------

def test_health_needs_nobody_and_everything_else_a_signed_in_person(panel):
    ask, _ = panel

    assert ask("GET", "/health", signed=False)[0] == 200
    assert ask("GET", "/state", signed=False)[0] == 401
    assert ask("GET", "/state", audience="heliograph")[0] == 401


def test_changing_the_world_needs_the_operate_permission(panel):
    ask, _ = panel

    status, shown = ask("GET", "/state", permissions=())
    assert status == 200 and shown["may_operate"] is False
    for path in ("/start", "/stop", "/command", "/discard"):
        assert ask("POST", path, {"pack": "probe"}, permissions=())[0] == 403


# -- what it says -------------------------------------------------------------

def test_with_no_world_it_offers_the_packs(panel):
    ask, directory = panel

    shown = ask("GET", "/state")[1]

    assert shown["phase"] == "stopped" and shown["resumable"] is False
    assert shown["directory"] == str(directory)
    assert {"probe", "retail", "field_service"} <= {p["name"] for p in shown["packs"]}
    assert all(p["description"] for p in shown["packs"])


def test_a_run_under_way_is_busy_even_before_it_answers(panel):
    # THE RUN LOCK, held from a run's first moment to its last: building
    # and tidying up read as busy, never as stopped.
    ask, directory = panel
    directory.mkdir()
    with open(directory / "run.lock", "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)

        assert ask("GET", "/state")[1]["phase"] == "busy"
        assert ask("POST", "/start", {"pack": "probe"})[0] == 409
        assert ask("POST", "/discard")[0] == 409


def test_a_world_left_without_tidying_up_is_not_answering(panel):
    ask, directory = panel
    directory.mkdir()
    (directory / "control.json").write_text(json.dumps({"url": "http://127.0.0.1:9", "token": "x", "pid": 1}))

    shown = ask("GET", "/state")[1]

    assert shown["phase"] == "not answering" and "not answering" in shown["problem"]


# -- what it refuses ----------------------------------------------------------

@pytest.mark.parametrize("body, said", [
    ({"pack": "nonsense"}, "no pack 'nonsense'"),
    ({"pack": "probe", "resume": True}, "no world to resume"),
    ({"pack": "probe", "days": -1}, "days must be 0 to 366"),
    ({"pack": "probe", "compression": 0}, "compression more than 0"),
    ({"pack": "probe", "days": "many"}, "must be numbers"),
])
def test_a_start_it_cannot_do_is_said(panel, body, said):
    ask, _ = panel

    status, shown = ask("POST", "/start", body)

    assert status == 409 and said in shown["detail"]


def test_with_no_world_there_is_no_schema_to_change(panel):
    ask, _ = panel

    status, said = ask("GET", "/schema")
    assert status == 409 and said["detail"]


def test_only_its_own_commands_pass_and_a_body_must_be_an_object(panel):
    ask, _ = panel

    # A standby's replay is the terminal's to pause, not the page's.
    assert "no command 'pause_replay' here" in \
        ask("POST", "/command", {"command": "pause_replay"})[1]["detail"]
    assert ask("POST", "/command", [1, 2])[0] == 400


# -- telling operators, through Elysium's Inbox ------------------------------

class _Panel:
    """The panel as the watcher sees it: a state, and where things live."""

    def __init__(self, data: Path) -> None:
        self.data, self.directory = data, data / "world"
        self.stop_marker = data / panel_server.STOP_ASKED_FILENAME
        self.phase, self.pack = "stopped", "probe"

    def state(self) -> dict:
        world = {"pack": self.pack} if self.phase == "running" else None
        return {"phase": self.phase, "world": world, "pack": self.pack}


@pytest.fixture
def watching(tmp_path):
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    panel = _Panel(tmp_path / "data")

    def watcher():
        return panel_server.Watcher(panel, {"outbox": str(outbox)})

    def posted() -> list[str]:
        return sorted(json.loads(f.read_text())["summary"] for f in outbox.glob("*.json"))

    return panel, watcher, posted


def _through(panel, watcher, *phases):
    for phase in phases:
        panel.phase = phase
        watcher.check()


def test_the_first_look_tells_nobody_anything(watching):
    panel, watcher, posted = watching
    panel.phase = "running"

    assert watcher().check() is None and posted() == []


def test_a_world_that_finished_building_is_told_to_everyone_who_may_operate_it(watching):
    panel, watcher, posted = watching
    _through(panel, watcher(), "stopped", "busy", "running")

    assert posted() == ["The simulated world (probe) is running"]
    notice = json.loads(next((panel.data.parent / "outbox").glob("*.json")).read_text())
    assert notice["to"] == "everyone"


def test_a_world_built_between_two_looks_is_told_too(watching):
    panel, watcher, posted = watching
    _through(panel, watcher(), "stopped", "running")

    assert posted() == ["The simulated world (probe) is running"]


def test_a_crash_is_told_even_when_it_happened_while_elysium_was_down(watching):
    panel, watcher, posted = watching
    _through(panel, watcher(), "running")

    # ELYSIUM, AND SO THIS SERVER, GONE; THE WORLD DIES; A NEW WATCHER.
    _through(panel, watcher(), "not answering")

    assert posted() == ["The simulated world (probe) stopped without tidying up"]


def test_a_world_that_never_got_going_is_told(watching):
    panel, watcher, posted = watching
    _through(panel, watcher(), "stopped", "busy", "stopped")

    assert posted() == ["The simulated world (probe) did not start"]


def test_a_stop_someone_asked_for_tells_nobody_even_while_it_was_building(watching):
    # STOPPED BEFORE IT EVER RAN, by somebody pressing Stop: without the
    # marker this would read as a world that did not start.
    panel, watcher, posted = watching
    watcher_ = watcher()
    _through(panel, watcher_, "stopped", "busy")
    panel.stop_marker.parent.mkdir(parents=True, exist_ok=True)
    panel.stop_marker.touch()

    _through(panel, watcher_, "stopped")

    assert posted() == [] and not panel.stop_marker.exists()


def test_a_world_stopped_from_outside_after_running_tells_nobody(watching):
    # SIGTERM from a terminal: whoever did it knows.
    panel, watcher, posted = watching
    _through(panel, watcher(), "running", "busy", "stopped")

    assert posted() == []


# -- a real world -------------------------------------------------------------

def _serve(directory: Path):
    start = directory.parent / "start.json"
    outbox = directory.parent / "outbox"
    outbox.mkdir(exist_ok=True)
    start.write_text(json.dumps(info(directory, outbox)))
    process = subprocess.Popen(
        [sys.executable, str(PANEL / "server.py")], cwd=PANEL, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        # A SESSION OF ITS OWN, as Elysium starts it, so the test can do
        # what Elysium does to stop it: signal its whole process group.
        start_new_session=True,
        env={"PATH": os.environ["PATH"], "HOME": str(directory.parent), "PORT": "0",
             "ELYSIUM_ADDON_START": str(start)})
    line = process.stdout.readline().decode()
    port = int(line.split("listening on ")[1].split(",")[0])
    return process, Client(port)


def _until(ask, phase: str, seconds: float = 180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        shown = ask("GET", "/state")[1]
        if shown["phase"] == phase:
            return shown
        time.sleep(0.5)
    raise AssertionError(f"never {phase}: {shown}")


@pytest.fixture
def world_directory(tmp_path):
    """Where the test's world lives -- and, however the test ends, no world
    left running there: a failure part-way would otherwise leave its
    database servers holding their ports."""
    from simulator.control import CONTROL_FILENAME, run_under_way

    directory = tmp_path / "world"
    yield directory
    if run_under_way(directory):
        try:
            os.kill(json.loads((directory / CONTROL_FILENAME).read_text())["pid"], signal.SIGTERM)
        except (OSError, ValueError, KeyError):
            pass
        deadline = time.monotonic() + 60
        while run_under_way(directory) and time.monotonic() < deadline:
            time.sleep(0.5)


@pytest.mark.postgres
def test_a_world_runs_on_while_the_panel_is_gone_and_is_found_again(world_directory, postgres_binaries,
                                                                   mariadb_binaries):
    directory = world_directory
    first, ask = _serve(directory)
    try:
        assert ask("POST", "/start", {"pack": "probe", "days": 1, "compression": 3600})[0] == 200
        running = _until(ask, "running")
        assert running["world"]["following"] is True
        assert set(running["connections"]["silos"]) == set(running["world"]["silos"])
        assert ask("POST", "/command", {"command": "speed", "compression": 7200})[1] == {"compression": 7200.0}
        # A SCHEMA CHANGE FROM THE PAGE: its fields reach the world, the
        # world's refusal comes back in its own words, and the change is
        # in what the page reads next.
        assert ask("POST", "/command", {"command": "drift", "operation": "add_column",
                                        "table": "ops.readings", "column": "remark",
                                        "type": "text", "length": 40})[1]["breaking"] is False
        refused = ask("POST", "/command", {"command": "drift", "operation": "drop_column",
                                           "table": "ops.nowhere", "column": "x"})
        assert refused[0] == 409 and "nowhere" in refused[1]["detail"]
        assert ask("POST", "/command", {
            "command": "drift", "operation": "add_table", "table": "ops.visits",
            "columns": {"visit_id": {"type": "text", "length": 64, "primary_key": True,
                                     "nullable": False}}})[0] == 200
        schema = ask("GET", "/schema")[1]
        assert schema["silos"]["ops"]["tables"]["visits"][0]["name"] == "visit_id"
        assert "remark" in {c["name"] for c in schema["silos"]["ops"]["tables"]["readings"]}
        assert [c["operation"] for c in schema["silos"]["ops"]["history"]] == ["AddColumn", "AddTable"]
        # ITS LOG AS IT GOES, not only once it stops: unbuffered.
        assert any("Following at" in line for line in ask("GET", "/log")[1]["lines"])
        # AND ITS OPERATORS TOLD it is running, through Elysium's Inbox.
        deadline = time.monotonic() + 3 * panel_server.WATCH_SECONDS
        while time.monotonic() < deadline and not list((directory.parent / "outbox").glob("*.json")):
            time.sleep(0.5)
        [ready] = (directory.parent / "outbox").glob("*.json")
        assert json.loads(ready.read_text())["summary"] == "The simulated world (probe) is running"
    finally:
        # ELYSIUM GOES, as hard as it can: SIGKILL to the panel server's
        # whole process group, as Elysium's supervisor sends at a deadline.
        # The world is in a session of its own and is not in that group.
        os.killpg(first.pid, signal.SIGKILL)
        first.wait()

    before = json.loads((directory / "control.json").read_text())["pid"]
    second, ask = _serve(directory)
    try:
        found = _until(ask, "running")
        assert found["world"]["compression"] == 7200.0
        assert json.loads((directory / "control.json").read_text())["pid"] == before

        assert ask("POST", "/stop")[1]["stopping"] is True
        # TIDYING UP is busy, not stopped: a Start now would build into it.
        assert ask("GET", "/state")[1]["phase"] in ("busy", "stopped")
        stopped = _until(ask, "stopped")
        assert stopped["resumable"] is True and stopped["pack"] == "probe"
        assert "built from probe, not retail" in ask("POST", "/start", {"pack": "retail", "resume": True})[1]["detail"]

        assert ask("POST", "/start", {"pack": "probe", "resume": True, "compression": 600})[0] == 200
        assert _until(ask, "running")["world"]["compression"] == 600.0
        ask("POST", "/stop")
        _until(ask, "stopped")
        assert ask("POST", "/discard")[1] == {"discarded": True}
        assert not directory.exists()
    finally:
        second.stdin.close()
        assert second.wait(timeout=10) == 0
