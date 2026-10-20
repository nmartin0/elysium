"""Operating a running world from outside it (simulator/control.py).

One world, built once for the module from the probe pack, which has a
source of every kind. The loop that would run it in `simulator run` is
stood in for by a thread that serves the queue, so every command here
goes the real way: over HTTP with the token, queued, carried out on the
world's thread.
"""

import csv
import json
import os
import stat
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from simulator import runner
from simulator.control import CONTROL_FILENAME, ControlError, Controller, ControlServer, send
from simulator.spec import load_pack

PROBE = Path(__file__).resolve().parents[1] / "packs" / "probe.yaml"

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def running(tmp_path_factory, postgres_binaries, mariadb_binaries):
    directory = tmp_path_factory.mktemp("control")
    world = runner.build(load_pack(PROBE), directory / "w", seed=3)
    stop = threading.Event()
    controller = Controller(world)
    server = ControlServer(controller, directory / "w")

    def loop():
        while not stop.is_set():
            controller.serve()
            time.sleep(0.02)

    serving = threading.Thread(target=loop, daemon=True)
    try:
        runner.seed(world)
        runner.run(world, total_seconds=26 * 3600, tick_seconds=3600)
        server.start()
        serving.start()
        yield world, directory / "w", controller
    finally:
        stop.set()
        if serving.is_alive():
            serving.join()
        controller.restore_everything()
        server.stop()
        runner.stop(world)


def _details(world, silo: str) -> dict:
    return dict(world.connections()[silo].details)


# -- the channel -------------------------------------------------------

def test_the_control_file_is_the_owners_alone_and_not_a_connection(running):
    world, directory, _ = running

    path = directory / CONTROL_FILENAME
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    published = json.dumps({name: d.details for name, d in world.connections().items()})
    assert json.loads(path.read_text())["token"] not in published


def test_a_wrong_token_is_refused(running):
    _, directory, _ = running
    url = json.loads((directory / CONTROL_FILENAME).read_text())["url"]
    request = urllib.request.Request(
        f"{url}/control", method="POST", data=b'{"command": "status"}',
        headers={"Authorization": "Bearer not-the-token"})

    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request, timeout=10)

    assert refused.value.code == 401


def test_an_unknown_command_is_said_back(running):
    _, directory, _ = running

    with pytest.raises(ControlError, match="no command 'explode'"):
        send(directory, "explode")


# -- time --------------------------------------------------------------

def test_pause_resume_and_advance(running):
    _, directory, _ = running

    assert send(directory, "pause")["paused"] is True
    assert send(directory, "status")["paused"] is True
    before = send(directory, "status")["elapsed_days"]
    send(directory, "advance", duration="1d")
    assert send(directory, "status")["elapsed_days"] == pytest.approx(before + 1)
    assert send(directory, "resume")["paused"] is False


def test_a_paused_world_does_not_tick(running, monkeypatch):
    from simulator import cli

    world, _, controller = running
    controller.paused = True
    ticked = []
    sleeps = []
    monkeypatch.setattr(cli.runner, "tick", lambda *a: ticked.append(a))

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 3:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", sleep)
    try:
        with pytest.raises(KeyboardInterrupt):
            cli._follow(world, 3600.0, 3600.0, controller)
    finally:
        controller.paused = False

    assert ticked == [] and len(sleeps) == 3


# -- a schema change applied live -------------------------------------

def test_a_live_rename_is_followed_by_the_business_and_its_exports(running):
    world, directory, _ = running

    applied = send(directory, "drift", operation="rename_column",
                   table="ops.readings", column="quantity", to="qty")
    send(directory, "advance", duration="2d")

    assert "qty" in applied["applied"]
    drop = world.silo("drop")
    newest = sorted(drop.listing())[-1]
    with (drop.path / newest).open(encoding="utf-8-sig", newline="") as handle:
        header = next(csv.reader(handle))
    assert "qty" in header and "quantity" not in header
    # Written after the rename, so the business wrote the new name.
    from simulator.relational import fetch_all
    recent = fetch_all(world.silo("ops"), world.database("ops"),
                       'SELECT count(*) FROM "readings" WHERE "qty" IS NOT NULL')[0][0]
    assert recent > 0


# -- outages -----------------------------------------------------------

def test_a_postgresql_outage_ends_open_sessions_and_refuses_new_ones(running):
    import psycopg

    world, directory, _ = running
    details = _details(world, "ops")

    def connect():
        return psycopg.connect(host=details["host"], port=details["port"],
                               dbname=details["database"], user=details["user"],
                               password=details["password"], connect_timeout=5)

    held = connect()
    try:
        send(directory, "outage", silo="ops")
        with pytest.raises(psycopg.Error) as ended:
            held.execute("SELECT 1")
        assert ended.value.sqlstate in ("57P01", None)  # None: the socket closed first
        with pytest.raises(psycopg.OperationalError):
            connect()
        assert send(directory, "status")["silos"]["ops"]["state"] == "out"
        # The business is not the reader: time still moves and rows land.
        send(directory, "advance", duration="6h")
    finally:
        held.close()
        send(directory, "restore", silo="ops")
    with connect() as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)


def test_a_mariadb_outage_locks_the_reader_out(running):
    import pymysql

    world, directory, _ = running
    details = _details(world, "shop")

    def connect():
        return pymysql.connect(host=details["host"], port=details["port"],
                               database=details["database"], user=details["user"],
                               password=details["password"], connect_timeout=5)

    send(directory, "outage", silo="shop")
    try:
        with pytest.raises(pymysql.err.OperationalError):
            connect()
    finally:
        send(directory, "restore", silo="shop")
    connect().close()


def test_a_rest_outage_answers_503_with_retry_after(running):
    world, directory, _ = running
    details = _details(world, "api")

    def get():
        headers = {"Authorization": f"Bearer {details['token']}"} if "token" in details else {}
        request = urllib.request.Request(f"{details['base_url']}/v1/readings", headers=headers)
        return urllib.request.urlopen(request, timeout=10)

    send(directory, "outage", silo="api")
    try:
        with pytest.raises(urllib.error.HTTPError) as down:
            get()
        assert down.value.code == 503
        assert int(down.value.headers["Retry-After"]) > 0
    finally:
        send(directory, "restore", silo="api")
    assert get().status == 200


def test_a_share_outage_hides_the_folder_and_keeps_what_was_exported(running):
    world, directory, _ = running
    home = Path(_details(world, "drop")["path"])
    before = set(world.silo("drop").listing())

    send(directory, "outage", silo="drop")
    try:
        assert not home.exists()
        send(directory, "advance", duration="2d")   # the daily export runs meanwhile
    finally:
        send(directory, "restore", silo="drop")

    assert home.is_dir()
    assert set(world.silo("drop").listing()) > before


def test_stopping_restores_every_outage(running):
    import psycopg

    world, directory, controller = running
    send(directory, "outage", silo="ops")

    # What the run loop does in its `finally`, called from here because
    # this module's world goes on; the serving thread is idle between
    # commands, so nothing else touches the world meanwhile.
    controller.restore_everything()

    details = _details(world, "ops")
    with psycopg.connect(host=details["host"], port=details["port"],
                         dbname=details["database"], user=details["user"],
                         password=details["password"], connect_timeout=5) as conn:
        assert conn.execute("SELECT 1").fetchone() == (1,)
    assert send(directory, "status")["silos"]["ops"]["state"] == "up"


# -- the oracle ---------------------------------------------------------

def test_the_oracle_is_readable_as_json(running):
    world, directory, _ = running

    series = send(directory, "oracle")

    assert set(series) == {watch.name for watch in world.oracle.watches}
    assert all(isinstance(sample["at"], str) for samples in series.values()
               for sample in samples)
