# SPDX-FileCopyrightText: 2026 Nicholas Martin
# SPDX-License-Identifier: LicenseRef-Proprietary

"""The engine started the way Elysium starts an add-on: a port in ``PORT``, a start
file named in ``ELYSIUM_ADDON_START``, a pipe as standard input. Requests are signed as
Elysium's proxy signs them (tests/support/elysium.py). Imports nothing from ``heliograph``."""

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support.elysium import HEADER, token, write_start_file
from tests.support.engine import Engine, trades_csv, trend_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def started(tmp_path: Path) -> Iterator[Engine]:
    """An engine as Elysium starts it: nothing given on the command line."""
    start = write_start_file(tmp_path / "elysium")
    engine = Engine(
        env={"ELYSIUM_ADDON_START": str(start), "PORT": "0", "HELIOGRAPH_DATA": ""},
        cwd=tmp_path,
        stdin=subprocess.PIPE,
    ).started()  # fmt: skip
    yield engine
    engine.close()


def signed(*permissions: str) -> dict[str, str]:
    return {HEADER: token(*permissions)}


def test_it_listens_where_elysium_said_and_says_it_is_an_add_on(started: Engine) -> None:
    listening = started.wait_for("listening")
    assert listening["addon"] == "heliograph"
    assert listening["host"] == "127.0.0.1"


def test_the_supervisors_health_check_needs_no_token_and_nothing_else_is_open(
    started: Engine,
) -> None:
    assert started.request("GET", "/api/health")[0] == 200
    for path in ("/api/backtests", "/api/plugins", "/api/configs"):
        status, body = started.request("GET", path)
        assert status == 401, path
        assert HEADER in body["error"]


def test_a_reader_reads_and_cannot_change_and_an_operator_can(
    started: Engine, tmp_path: Path
) -> None:
    assert started.request("GET", "/api/backtests", headers=signed("use")) == (
        200,
        {"backtests": []},
    )
    assert started.request("POST", "/api/backtests", {}, signed("use"))[0] == 403
    assert started.request("POST", "/api/backtests", {}, signed("operate"))[0] == 400


def test_the_data_lives_in_the_folder_elysium_gave(started: Engine, tmp_path: Path) -> None:
    assert (tmp_path / "elysium" / "data" / "runs").is_dir()


def test_a_finished_backtest_drops_one_notice_in_the_inbox_outbox(
    started: Engine, tmp_path: Path
) -> None:
    data = trades_csv(tmp_path / "btc.csv", 2 * 24 * 60)
    text = trend_config(data, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    status, queued = started.request(
        "POST", "/api/backtests", {"config": text, "name": "mine"}, signed("operate")
    )
    assert status == 202
    run = queued["id"]
    notice = tmp_path / "elysium" / "outbox" / f"backtest-{run}.json"
    started.polling(notice.exists)
    assert json.loads(notice.read_text()) == {
        "to": "everyone",
        "summary": f"Backtest {run} finished",
    }
    assert [p.name for p in notice.parent.iterdir()] == [notice.name]  # nothing half written


def test_a_failed_backtest_says_why_in_the_notice(started: Engine, tmp_path: Path) -> None:
    text = trend_config(tmp_path / "missing.csv", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
    run = started.request("POST", "/api/backtests", {"config": text}, signed("operate"))[1]["id"]
    notice = tmp_path / "elysium" / "outbox" / f"backtest-{run}.json"
    started.polling(notice.exists)
    body = json.loads(notice.read_text())
    assert body["summary"] == f"Backtest {run} failed"
    assert body["detail"]


def test_the_server_leaves_with_status_0_when_elysium_goes(started: Engine) -> None:
    """Elysium's end of the pipe closing, as when Elysium is killed."""
    assert started.process.stdin is not None
    started.process.stdin.close()
    assert started.wait() == 0
    assert "stopped" in [e["event"] for e in started.events()]


def test_it_stops_on_sigterm_with_status_0_as_elysium_stops_it(started: Engine) -> None:
    assert started.stop() == 0


def test_standalone_still_ignores_port_and_asks_for_no_token(tmp_path: Path) -> None:
    engine = Engine(
        "--data", str(tmp_path / "d"), "--port", "0",
        env={"PORT": "1"},
        cwd=ROOT,
    ).started()  # fmt: skip
    try:
        assert engine.get("/api/backtests") == {"backtests": []}
        assert "addon" not in engine.wait_for("listening")
    finally:
        engine.close()
