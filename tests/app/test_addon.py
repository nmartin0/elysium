# SPDX-FileCopyrightText: 2026 Nicholas Martin
# SPDX-License-Identifier: LicenseRef-Proprietary

"""Heliograph as an Elysium add-on: the identity guard, the start file, the outbox and
the settings add-on mode gives. Tokens are made as Elysium's ``sign_identity`` makes
them (tests/support/elysium.py); the process is tested from outside in tests/process."""

import asyncio
import base64
import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from heliograph.app import addon
from heliograph.app.addon import (
    AddonStart,
    NotSignedInError,
    Outbox,
    exit_when_elysium_does,
    notice_name,
    verify,
)
from heliograph.app.config import ConfigError
from heliograph.app.server import Backtests, Settings, make_app, settings_from
from heliograph.core.clock import SimulatedClock
from heliograph.core.time import Timestamp
from tests.support import elysium
from tests.support.elysium import HEADER, SECRET, sign_identity, write_start_file

NOW = 1_800_000_000
CLOCK = SimulatedClock(Timestamp(NOW * 1_000_000_000))

# Made by Elysium's own sign_identity (348414e0) for these inputs.
ELYSIUM_MADE = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhdWQiOiJoZWxpb2dyYXBoIiwiZXhwIjoxMDYwLCJpYXQiOjEwMDAs"
    "ImlzcyI6ImVseXNpdW0iLCJuYW1lIjoiYWxpY2UiLCJwZXJtaXNzaW9ucyI6WyJtb2R1bGU6aGVsaW9ncmFwaDp1c2Ui"
    "XSwic3ViIjoiYWxpY2UifQ.v25awVaih-geeR8v7P534wF_6RVmKh2gFRayg_vL6UI"
)


def token(*permissions: str) -> str:
    """A good token, made at the simulated clock's time."""
    return elysium.token(*permissions, now=NOW)


@pytest.fixture
def start(tmp_path: Path) -> AddonStart:
    found = AddonStart.from_environment({addon.START_VARIABLE: str(write_start_file(tmp_path))})
    assert found is not None
    return found


def client(tmp_path: Path, start: AddonStart | None) -> httpx.AsyncClient:
    settings = Settings(data=tmp_path, addon=start)
    app = make_app(settings, CLOCK, Backtests(tmp_path / "runs", CLOCK))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://engine")


def ask(
    tmp_path: Path,
    start: AddonStart | None,
    path: str,
    *,
    method: str = "GET",
    signed: str | None = None,
) -> httpx.Response:
    async def go() -> httpx.Response:
        async with client(tmp_path, start) as http:
            headers = {} if signed is None else {HEADER: signed}
            return await http.request(method, path, headers=headers)

    return asyncio.run(go())


# -- the token ----------------------------------------------------------------------


def test_a_token_made_by_elysium_is_taken(start: AddonStart) -> None:
    other = start.__class__(
        id=start.id, port=0, header=HEADER, secret="s3cret", issuer="elysium",
        audience="heliograph", options={}, data_dir=start.data_dir, outbox=None,
    )  # fmt: skip
    who = verify(ELYSIUM_MADE, other, now=1000)
    assert who.user == "alice"
    assert who.holds("use")
    assert not who.holds("operate")


def test_this_side_signs_exactly_as_elysium_does() -> None:
    made = sign_identity(
        "s3cret", audience="heliograph", user_id="alice", now=1000,
        permissions=["module:heliograph:use"],
    )  # fmt: skip
    assert made == ELYSIUM_MADE


def made(secret: str = SECRET, **changes: Any) -> str:
    given: dict[str, Any] = {"audience": "heliograph", "user_id": "a", "now": NOW} | changes
    return sign_identity(secret, **given)


@pytest.mark.parametrize(
    ("make", "says"),
    [
        (lambda: made("another-secret"), "signature"),
        (lambda: made(audience="simulator"), "another add-on"),
        (lambda: made(issuer="x"), "Elysium"),
        (lambda: made(now=NOW - 100), "expired"),
        (lambda: made(now=NOW + 100), "future"),
        (lambda: made(user_id=""), "nobody"),
        (lambda: "not.a.token", "not a token"),
        (lambda: "one-piece", "not a token"),
    ],
)
def test_a_token_that_is_not_elysiums_for_this_add_on_now_is_refused(
    start: AddonStart, make: Callable[[], str], says: str
) -> None:
    candidate = make()
    with pytest.raises(NotSignedInError, match=says):
        verify(candidate, start, now=NOW)


def test_a_token_nested_deep_enough_to_exhaust_the_parser_is_refused_as_not_a_token(
    start: AddonStart,
) -> None:
    deep = base64.urlsafe_b64encode(b"[" * 100_000).rstrip(b"=").decode()
    with pytest.raises(NotSignedInError, match="not a token"):
        verify(f"{deep}.{deep}.{deep}", start, now=NOW)


def test_a_token_said_to_need_no_signature_is_refused(start: AddonStart) -> None:
    def part(value: object) -> str:
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    claims = {"iss": "elysium", "aud": "heliograph", "sub": "mallory", "iat": NOW, "exp": NOW + 60}
    unsigned = f"{part({'alg': 'none'})}.{part(claims)}."
    with pytest.raises(NotSignedInError, match="HS256"):
        verify(unsigned, start, now=NOW)


def test_a_token_a_few_seconds_late_is_still_good(start: AddonStart) -> None:
    made = sign_identity(SECRET, audience="heliograph", user_id="a", now=NOW - 63)
    assert verify(made, start, now=NOW).user == "a"
    late = sign_identity(SECRET, audience="heliograph", user_id="a", now=NOW - 66)
    with pytest.raises(NotSignedInError, match="expired"):
        verify(late, start, now=NOW)


# -- the guard ----------------------------------------------------------------------


def test_health_answers_without_a_token_so_the_supervisor_can_ask(
    tmp_path: Path, start: AddonStart
) -> None:
    assert ask(tmp_path, start, "/api/health").status_code == 200


def test_the_open_health_answer_does_not_name_a_run(tmp_path: Path, start: AddonStart) -> None:
    assert "running" not in ask(tmp_path, start, "/api/health").json()


def test_everything_else_is_refused_without_a_token(tmp_path: Path, start: AddonStart) -> None:
    for path in ("/api/backtests", "/api/plugins", "/api/configs", "/nothing/here"):
        answer = ask(tmp_path, start, path)
        assert answer.status_code == 401, path
        assert "X-Elysium-Identity" in answer.json()["error"]


def test_a_post_to_the_health_path_is_not_the_exempt_request(
    tmp_path: Path, start: AddonStart
) -> None:
    assert ask(tmp_path, start, "/api/health", method="POST").status_code == 401


def test_a_forged_token_is_refused(tmp_path: Path, start: AddonStart) -> None:
    forged = made("guess")
    assert ask(tmp_path, start, "/api/backtests", signed=forged).status_code == 401


def test_reading_takes_the_use_permission_and_changing_takes_operate(
    tmp_path: Path, start: AddonStart
) -> None:
    assert ask(tmp_path, start, "/api/backtests", signed=token("use")).status_code == 200
    assert ask(tmp_path, start, "/api/backtests", signed=token()).status_code == 403
    only_use = ask(tmp_path, start, "/api/backtests", method="POST", signed=token("use"))
    assert only_use.status_code == 403
    assert "operate" in only_use.json()["error"]
    # Past the guard, the API answers as ever: here that the body is not a request.
    assert (
        ask(tmp_path, start, "/api/backtests", method="POST", signed=token("operate")).status_code
        == 400
    )


def test_a_websocket_is_refused(tmp_path: Path, start: AddonStart) -> None:
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "websocket.connect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    app = make_app(Settings(data=tmp_path, addon=start), CLOCK, Backtests(tmp_path / "r", CLOCK))
    asyncio.run(app({"type": "websocket", "path": "/api/x", "headers": []}, receive, send))  # type: ignore[arg-type]
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_standalone_asks_for_no_token(tmp_path: Path) -> None:
    """Without Elysium the API is as it always was."""
    assert ask(tmp_path, None, "/api/backtests").status_code == 200


# -- the start file and the settings -----------------------------------------------


def test_no_start_variable_is_no_add_on_mode() -> None:
    assert AddonStart.from_environment({}) is None


def test_a_start_variable_set_but_empty_stops_the_server_rather_than_leaving_it_open() -> None:
    with pytest.raises(ConfigError, match="set but empty"):
        AddonStart.from_environment({addon.START_VARIABLE: ""})


def test_a_start_file_that_is_not_the_contract_is_said_so(tmp_path: Path) -> None:
    def load(text: str) -> None:
        path = tmp_path / "start.json"
        path.write_text(text)
        AddonStart.from_environment({addon.START_VARIABLE: str(path)})

    with pytest.raises(ConfigError, match="cannot read"):
        AddonStart.from_environment({addon.START_VARIABLE: str(tmp_path / "nowhere")})
    with pytest.raises(ConfigError, match="cannot read"):
        load("{not json")
    with pytest.raises(ConfigError, match="contract 2"):
        load('{"contract": 2}')
    with pytest.raises(ConfigError, match="not 'heliograph'"):
        load('{"contract": 1, "id": "simulator"}')
    with pytest.raises(ConfigError, match="not as expected"):
        load("[]")
    with pytest.raises(ConfigError, match="not as expected"):
        load('{"contract": 1, "id": "heliograph"}')
    good = json.loads(write_start_file(tmp_path / "g").read_text())
    with pytest.raises(ConfigError, match="options"):
        load(json.dumps({**good, "options": 3}))
    with pytest.raises(ConfigError, match="needs a header and a secret"):
        load(json.dumps({**good, "identity": {**good["identity"], "secret": ""}}))


def test_the_secret_is_not_in_the_start_values_text(start: AddonStart) -> None:
    assert SECRET not in repr(start)


def test_in_add_on_mode_the_data_folder_and_port_come_from_elysium(tmp_path: Path) -> None:
    file = write_start_file(tmp_path, port=4321)
    environ = {addon.START_VARIABLE: str(file), "PORT": "5555"}
    settings = settings_from(None, None, None, None, environ)
    assert settings.data == tmp_path / "data"
    assert settings.port == 5555
    assert settings.configs is None
    assert settings.addon is not None
    # Without PORT, the start file's own.
    environ.pop("PORT")
    assert settings_from(None, None, None, None, environ).port == 4321


def test_a_deployments_options_name_the_data_and_configurations(tmp_path: Path) -> None:
    file = write_start_file(
        tmp_path, options={"data": str(tmp_path / "mine"), "configs": str(tmp_path / "cfg")}
    )
    settings = settings_from(None, None, None, None, {addon.START_VARIABLE: str(file)})
    assert (settings.data, settings.configs) == (tmp_path / "mine", tmp_path / "cfg")


def test_the_engines_own_options_beat_the_start_files(tmp_path: Path) -> None:
    file = write_start_file(tmp_path, port=4321, options={"data": "from-options"})
    environ = {addon.START_VARIABLE: str(file), "PORT": "5555", "HELIOGRAPH_PORT": "6666"}
    settings = settings_from("given", None, None, None, environ)
    assert (str(settings.data), settings.port) == ("given", 6666)
    assert settings_from("given", None, None, 7, environ).port == 7


def test_standalone_ignores_the_port_variable(tmp_path: Path) -> None:
    """PORT means something to many programs; only Elysium's start gives it meaning here."""
    settings = settings_from(str(tmp_path), None, None, None, {"PORT": "5555"})
    assert settings.port == 8765
    assert settings.addon is None


def test_a_bad_assigned_port_is_named(tmp_path: Path) -> None:
    file = write_start_file(tmp_path)
    with pytest.raises(ConfigError, match="PORT must be a port number"):
        settings_from(None, None, None, None, {addon.START_VARIABLE: str(file), "PORT": "x"})


def test_add_on_mode_listens_on_this_computer_only(tmp_path: Path) -> None:
    file = write_start_file(tmp_path)
    environ = {addon.START_VARIABLE: str(file)}
    for host in ("127.0.0.1", "::1", "localhost"):
        assert settings_from(None, None, host, None, environ).host == host
    with pytest.raises(ConfigError, match="this computer only"):
        settings_from(None, None, "0.0.0.0", None, environ)
    # Standalone keeps its right to listen elsewhere.
    assert settings_from(str(tmp_path), None, "0.0.0.0", None, {}).host == "0.0.0.0"


# -- the outbox ---------------------------------------------------------------------


@pytest.fixture
def outbox(tmp_path: Path) -> Outbox:
    (tmp_path / "out").mkdir()
    return Outbox(tmp_path / "out")


def test_a_notice_is_one_whole_file_named_by_its_key(outbox: Outbox) -> None:
    path = outbox.post("backtest-a", "Backtest a finished")
    assert path == outbox.folder / "backtest-a.json"
    assert json.loads(path.read_text()) == {"to": "everyone", "summary": "Backtest a finished"}
    assert [p.name for p in outbox.folder.iterdir()] == ["backtest-a.json"]  # no .part left


def test_the_same_run_told_twice_is_the_same_file(outbox: Outbox) -> None:
    outbox.backtest_finished("trend-20261101T000000Z", None)
    outbox.backtest_finished("trend-20261101T000000Z", None)
    assert [p.name for p in outbox.folder.iterdir()] == ["backtest-trend-20261101T000000Z.json"]


def test_a_failure_carries_its_reason_as_detail(outbox: Outbox) -> None:
    outbox.backtest_finished("r1", "no data " * 1000)
    body = json.loads((outbox.folder / "backtest-r1.json").read_text())
    assert body["summary"] == "Backtest r1 failed"
    assert len(body["detail"]) == addon.NOTICE_DETAIL


def test_a_long_summary_is_cut_to_what_elysium_takes(outbox: Outbox) -> None:
    outbox.post("n", "x" * 500)
    assert len(json.loads((outbox.folder / "n.json").read_text())["summary"]) == 200


def test_a_name_elysium_would_refuse_is_refused_here(outbox: Outbox) -> None:
    for bad in ("", "a.b", "a/b", "x" * 101):
        with pytest.raises(ValueError, match="outbox name"):
            outbox.post(bad, "s")


def test_a_run_id_elysium_cannot_use_as_a_name_gets_a_stable_distinct_one() -> None:
    plain = notice_name("trend-20261101T000000Z")
    assert plain == "backtest-trend-20261101T000000Z"
    dotted, other = notice_name("my.cfg-20261101T000000Z"), notice_name("my_cfg-20261101T000000Z")
    assert dotted == notice_name("my.cfg-20261101T000000Z")
    assert "." not in dotted
    assert dotted != other
    long_one, long_two = notice_name("a" * 120 + "1"), notice_name("a" * 120 + "2")
    assert len(long_one) <= 100
    assert long_one != long_two


# -- the backtest tells the outbox --------------------------------------------------


def test_a_backtest_that_ends_tells_who_asked_and_a_failing_teller_costs_nothing(
    tmp_path: Path,
) -> None:
    told: list[tuple[str, str | None]] = []
    done = threading.Event()

    def tell(run: str, error: str | None) -> None:
        told.append((run, error))
        if len(told) == 1:
            raise RuntimeError("the outbox is full")
        done.set()

    from heliograph.app.config import parse_config

    text = Path("tests/app/test_server.py").read_text().split('CONFIG = """')[1].split('"""')[0]
    backtests = Backtests(tmp_path / "runs", CLOCK, tell)
    backtests.start()
    first = backtests.submit("a", parse_config(text))
    second = backtests.submit("b", parse_config(text))
    assert done.wait(30)
    backtests.stop()
    assert backtests.wait(10.0)
    assert [run for run, _ in told] == [first.id, second.id]
    assert all(error for _, error in told)  # the file it names is not there: both failed


# -- standard input -----------------------------------------------------------------


def test_the_server_leaves_when_the_pipe_from_elysium_closes() -> None:
    reads = iter([b""])
    left = threading.Event()
    exit_when_elysium_does(left.set, lambda fd, n: next(reads))
    assert left.wait(10)


def test_the_pipe_being_unreadable_also_means_elysium_is_gone() -> None:
    left = threading.Event()

    def broken(fd: int, n: int) -> bytes:
        raise OSError("closed")

    exit_when_elysium_does(left.set, broken)
    assert left.wait(10)


def test_the_pipe_staying_open_keeps_the_server() -> None:
    release = threading.Event()
    left = threading.Event()

    def quiet(fd: int, n: int) -> bytes:
        release.wait(10)
        return b""

    thread = exit_when_elysium_does(left.set, quiet)
    assert not left.wait(0.2)
    release.set()
    thread.join(10)
    assert left.is_set()
