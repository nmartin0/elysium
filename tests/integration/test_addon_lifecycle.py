"""An add-on's server kept running by Elysium (BLOCKING.md item 3, step
2.2, api/addon_servers.py): started with what the contract promises,
restarted with back-off when it fails, stopped with a deadline, one
worker supervising it, following the configuration -- and shown and
restarted from the System sub-app.

REAL PROCESSES: the example add-on (tests/addons/echo) started by the
supervisor as a deployment's would be. The rounds are driven by the
test, and the back-off shortened, so each case takes about a second.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

import api.addon_servers as addon_servers
from api.addon_servers import (
    START_FILENAME,
    STATE_FILENAME,
    Supervisor,
    addon_directory,
    forward,
    log_path,
    read_state,
)
from core.modules import ModuleError, _load_manifest, load_addon_options
from tests.conftest import read_audit_log
from tests.integration.test_addon_proxy import ECHO, write_modules
from tests.integration.test_api import _csrf_headers, _login
from tests.integration.test_editing_config_from_the_ui import _grant, config_dir  # noqa: F401


@pytest.fixture(autouse=True)
def quick_back_off(monkeypatch):
    monkeypatch.setattr(addon_servers, "FIRST_BACKOFF_SECONDS", 0.2)
    monkeypatch.setattr(addon_servers, "MAX_BACKOFF_SECONDS", 0.8)
    monkeypatch.setattr(addon_servers, "HEALTH_EVERY_SECONDS", 0.2)


def echo_module(tmp_path: Path, **server):
    """The example add-on, its manifest's server changed as asked."""
    folder = tmp_path / "echo"
    if not folder.exists():
        shutil.copytree(ECHO, folder)
        # Its server finds the SDK from where it lives in this repository.
        (folder / "server.py").write_text((ECHO / "server.py").read_text().replace(
            "Path(__file__).resolve().parents[3]", f"Path({str(Path(ECHO).parents[2])!r})"))
    manifest = json.loads((ECHO / "module.json").read_text())
    manifest["server"].update(server)
    (folder / "module.json").write_text(json.dumps(manifest))
    return _load_manifest(folder)


class World:
    """A supervisor over a data and log directory, with what it should run."""

    def __init__(self, tmp_path: Path) -> None:
        self.data, self.logs = tmp_path / "data", tmp_path / "logs"
        self.wanted: list = []
        self.supervisors: list[Supervisor] = []

    def supervisor(self) -> Supervisor:
        made = Supervisor(self.data, self.logs, lambda: list(self.wanted))
        self.supervisors.append(made)
        return made

    def state(self, module_id: str = "echo") -> dict:
        return read_state(self.data, module_id) or {}

    def log(self, module_id: str = "echo") -> str:
        path = log_path(self.logs, module_id)
        return path.read_text() if path.exists() else ""

    def until(self, check, supervisor: "Supervisor | None" = None, seconds: float = 15.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for each in ([supervisor] if supervisor else self.supervisors):
                each.round()
            if check():
                return
            time.sleep(0.05)
        raise AssertionError(f"not reached in {seconds} s; state {self.state()}; log:\n{self.log()}")

    def ask(self, path: str, user: str = "ada"):
        upstream = forward(self.data, "echo", user, method="GET", path=path, query="", headers=[], body=b"")
        return json.loads(b"".join(upstream.body()))


@pytest.fixture
def world(tmp_path):
    made = World(tmp_path)
    yield made
    for supervisor in made.supervisors:
        supervisor.close()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A ZOMBIE IS NOT ALIVE: the supervisor reaps what it starts, so
    # one left would be a finding of its own -- said by its state.
    with open(f"/proc/{pid}/stat") as handle:
        return handle.read().split(")")[-1].split()[0] != "Z"


def test_it_starts_the_server_with_what_the_contract_promises(world, tmp_path, monkeypatch):
    monkeypatch.setenv("ELYSIUM_SILO_PASSWORD", "not for add-ons")
    world.wanted = [(echo_module(tmp_path), {"world": "/srv/sim"})]
    supervisor = world.supervisor()

    world.until(lambda: world.state().get("state") == "running")

    start = addon_directory(world.data, "echo") / START_FILENAME
    assert stat.S_IMODE(start.stat().st_mode) == 0o600
    assert stat.S_IMODE((addon_directory(world.data, "echo") / STATE_FILENAME).stat().st_mode) == 0o600
    shown = world.ask("start")
    assert shown["options"] == {"world": "/srv/sim"} and shown["id"] == "echo"
    assert Path(shown["dataDir"]).is_dir()
    # A BARE ENVIRONMENT: none of Elysium's own variables reach it.
    names = world.ask("env")
    assert "ELYSIUM_SILO_PASSWORD" not in names
    assert {"PORT", "ELYSIUM_ADDON_START"} <= set(names)
    assert world.ask("whoami")["user"] == "ada"
    assert "started, pid" in world.log() and "healthy" in world.log()
    assert supervisor is world.supervisors[0]


def test_one_that_exits_is_restarted_with_back_off_and_its_status_kept(world, tmp_path):
    world.wanted = [(echo_module(tmp_path), {"exit_after": 0.6})]
    world.supervisor()

    world.until(lambda: world.state().get("restarts", 0) >= 2)

    state = world.state()
    assert state["lastExit"] == 3
    log = world.log()
    assert "exited with status 3" in log
    # DOUBLING: the first wait, then twice it.
    assert "restarting in 0.2 s" in log and "restarting in 0.4 s" in log


def test_one_never_healthy_is_replaced(world, tmp_path, monkeypatch):
    monkeypatch.setattr(addon_servers, "START_SECONDS", 0.5)
    world.wanted = [(echo_module(tmp_path), {"health": "never"})]
    world.supervisor()

    world.until(lambda: world.state().get("restarts", 0) >= 1)

    assert "not healthy after 0.5 s" in world.log()
    assert world.state()["state"] in ("backing-off", "starting")


def test_a_command_that_is_not_there_is_said_and_tried_again(world, tmp_path):
    world.wanted = [(echo_module(tmp_path, command=["./no-such-program"]), {})]
    world.supervisor()

    world.until(lambda: world.state().get("restarts", 0) >= 2)

    assert "could not start" in world.log()


def test_stopping_asks_politely_first(world, tmp_path):
    world.wanted = [(echo_module(tmp_path), {})]
    supervisor = world.supervisor()
    world.until(lambda: world.state().get("state") == "running")
    pid = world.state()["pid"]

    supervisor.close()

    assert not _alive(pid)
    # AND LEFT CLEANLY: status 0. A server that tidied up and then
    # aborted at interpreter shutdown -- the SDK's stdin watcher once made
    # it do so -- would say "stopped cleanly" and still exit -6.
    assert "echo stopped cleanly" in world.log() and "SIGKILL" not in world.log()
    assert "stopped, status 0" in world.log()
    assert world.state()["state"] == "stopped" and world.state()["url"] is None


def test_one_ignoring_sigterm_is_killed_at_its_deadline(world, tmp_path):
    world.wanted = [(echo_module(tmp_path, stopSeconds=1), {"ignore_term": True})]
    supervisor = world.supervisor()
    world.until(lambda: world.state().get("state") == "running")
    pid = world.state()["pid"]

    began = time.monotonic()
    supervisor.close()
    took = time.monotonic() - began

    alive = _alive(pid)
    if alive:
        os.killpg(pid, 9)  # left by broken code; not by the test
    assert not alive
    assert 0.9 < took < 5, took
    assert "still running 1 s after SIGTERM; SIGKILL" in world.log()


def test_the_server_leaves_when_elysium_does_even_killed_outright(tmp_path):
    # THE STANDARD-INPUT PIPE (sdk/python/elysium_addon.py): its closing
    # is all that is left to say Elysium went when nothing sent SIGTERM.
    module = echo_module(tmp_path)
    start = tmp_path / "start.json"
    start.write_text(json.dumps({"contract": 1, "id": "echo", "options": {}, "identity": {
        "header": "X-Elysium-Identity", "secret": "s", "issuer": "elysium", "audience": "echo"}}))
    process = subprocess.Popen([sys.executable, "server.py"], cwd=module.folder, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, env={"PORT": "0", "ELYSIUM_ADDON_START": str(start),
                                                            "PATH": os.environ["PATH"]})
    try:
        assert b"listening" in process.stdout.readline()

        process.stdin.close()

        assert process.wait(timeout=10) == 0
    finally:
        # NOTHING LEFT BEHIND when the code under test is broken: this
        # file's controls break exactly this, and the process would
        # otherwise outlive the run.
        process.kill()
        process.wait()


def test_it_follows_the_configuration_off_on_and_changed(world, tmp_path):
    module = echo_module(tmp_path)
    world.wanted = [(module, {"n": 1})]
    world.supervisor()
    world.until(lambda: world.state().get("state") == "running")
    first = world.state()["pid"]

    world.wanted = []
    world.until(lambda: world.state().get("state") == "stopped")
    assert not _alive(first)

    world.wanted = [(module, {"n": 1})]
    world.until(lambda: world.state().get("state") == "running")
    second = world.state()["pid"]

    world.wanted = [(module, {"n": 2})]
    world.until(lambda: world.state().get("state") == "running" and world.state()["pid"] != second)
    assert world.ask("start")["options"] == {"n": 2}
    assert not _alive(second)


def test_one_worker_runs_it_and_another_takes_over_when_that_one_goes(world, tmp_path):
    world.wanted = [(echo_module(tmp_path), {})]
    first, second = world.supervisor(), world.supervisor()
    world.until(lambda: world.state().get("state") == "running")
    for _ in range(5):
        first.round()
        second.round()
    assert world.log().count("started, pid") == 1
    pid = world.state()["pid"]

    first.close()
    world.until(lambda: world.state().get("state") == "running" and world.state()["pid"] != pid,
                supervisor=second)

    assert world.log().count("started, pid") == 2


def test_a_restart_asked_for_is_done_at_once(world, tmp_path):
    world.wanted = [(echo_module(tmp_path), {})]
    world.supervisor()
    world.until(lambda: world.state().get("state") == "running")
    pid = world.state()["pid"]

    addon_servers.request_restart(world.data, "echo")
    world.until(lambda: world.state().get("state") == "running" and world.state()["pid"] != pid)

    assert "restart asked for" in world.log()
    assert world.state()["restarts"] == 0  # asked for, not a failure


# --- addons.yaml ------------------------------------------------------------


def test_options_come_from_addons_yaml_with_secrets_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("SIM_TOKEN", "t0ken")
    (tmp_path / "addons.yaml").write_text("echo:\n  options:\n    world: /srv\n    token: ${SIM_TOKEN}\n")

    options = load_addon_options(tmp_path, [echo_module(tmp_path / "m")])

    assert dict(options["echo"]) == {"world": "/srv", "token": "t0ken"}


@pytest.mark.parametrize("text, said", [
    ("browse:\n  options: {}\n", "not a listed module with a server"),
    ("echo:\n  port: 3\n", "takes only `options:`"),
    ("echo:\n  options:\n    password: hunter2\n", "literal credential"),
    ("echo:\n  options:\n    token: ${NOT_SET_ANYWHERE}\n", "NOT_SET_ANYWHERE"),
])
def test_a_mistake_in_addons_yaml_stops_the_load_with_its_name(tmp_path, text, said):
    (tmp_path / "addons.yaml").write_text(text)

    with pytest.raises(ModuleError, match="addons.yaml") as refused:
        load_addon_options(tmp_path, [echo_module(tmp_path / "m")])
    assert said in str(refused.value)


# --- the app and the System sub-app ---------------------------------------


@pytest.fixture
def deployment(config_dir, request):  # noqa: F811
    write_modules(config_dir, ECHO)
    (config_dir / "addons.yaml").write_text("echo:\n  options:\n    events: 2\n")
    client = request.getfixturevalue("client")
    _grant(client)
    client.app.state.user_directory.create_user("ops", "correct-pw", "us-west", "deployer")
    client.app.state.user_directory.create_user("alice", "correct-pw", None, "customer_service")
    return client


def _running(client) -> bool:
    return (read_state(client.app.state.runtime_paths.data_dir, "echo") or {}).get("state") == "running"


def _wait(check, seconds: float = 15.0) -> None:
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "not reached"
        time.sleep(0.1)


def test_the_app_starts_its_add_ons_and_stops_them_on_the_way_out(deployment):
    with deployment:
        _wait(lambda: _running(deployment))
        pid = read_state(deployment.app.state.runtime_paths.data_dir, "echo")["pid"]
        _login(deployment, "alice", "correct-pw")
        assert deployment.get("/api/addons/echo/whoami").json()["user"] == "alice"

    assert not _alive(pid)
    assert read_state(deployment.app.state.runtime_paths.data_dir, "echo")["state"] == "stopped"


def test_the_system_page_shows_each_server_and_restarts_one(deployment):
    with deployment:
        _wait(lambda: _running(deployment))
        _login(deployment, "ops", "correct-pw")

        shown = deployment.get("/api/system/addons").json()["addons"]
        assert [(a["id"], a["state"], a["enabled"]) for a in shown] == [("echo", "running", True)]
        # Never its secret, address or process.
        assert set(shown[0]) == {"id", "name", "enabled", "state", "since", "restarts", "last_exit",
                                 "next_start_at"}
        assert any("healthy" in line for line in deployment.get("/api/system/addons/echo/log").json()["lines"])

        response = deployment.post("/api/system/addons/echo/restart", headers=_csrf_headers(deployment))

        assert response.status_code == 202
        lines = lambda: deployment.get("/api/system/addons/echo/log").json()["lines"]  # noqa: E731
        _wait(lambda: any("restart asked for" in line for line in lines()))
        assert any(e.get("stage") == "addon_restart" and e.get("module") == "echo" and e.get("user_id") == "ops"
                   for e in read_audit_log(deployment.app.state.runtime_paths.log_dir))
        assert deployment.post("/api/system/addons/browse/restart",
                               headers=_csrf_headers(deployment)).status_code == 404


def test_the_system_routes_are_for_manage_deployment_only(deployment):
    _login(deployment, "alice", "correct-pw")

    assert deployment.get("/api/system/addons").status_code == 403
    assert deployment.get("/api/system/addons/echo/log").status_code == 403
    assert deployment.post("/api/system/addons/echo/restart", headers=_csrf_headers(deployment)).status_code == 403
