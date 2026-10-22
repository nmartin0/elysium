"""
addon_servers.py  (forwarding to an add-on's own server, and keeping it
running)

BLOCKING.md item 3, step 2. core/addons.py says what an add-on's server
is, what its token says and which headers pass; this is the part with
sockets and processes.

THE STATE FILE IS THE MEETING POINT. Each add-on with a server has a
directory, `<data dir>/addons/<module id>/`, and in it `server.json`,
readable by Elysium's own user only:

    {"state": "running", "url": "http://127.0.0.1:8123",
     "secret": "...", "pid": 4242, "since": ..., "restarts": 0, ...}

The supervisor writes it; the proxy reads it. So with several workers
the proxy in any of them reaches the server one of them started -- they
already coordinate through files on the shared data directory (README,
"One machine") -- and the proxy needs nothing of the supervisor but
that file.

THE PROXY HOLDS A THREAD WHILE IT WAITS, because `requests` -- already a
runtime dependency -- blocks. For an ordinary request that is the same
as any synchronous route. For an EVENT STREAM, open for minutes, it is
a thread of the pool every synchronous route shares, so:

  - at most STREAMS_PER_WORKER streams are open through one worker; one
    more is a 503 saying so, rather than a pool slowly starved;
  - each ends after MAX_STREAM_SECONDS, as Elysium's own /api/events
    does (api/live_updates.py): the browser's EventSource reconnects,
    through the session check and with a fresh token, so a revoked
    session stops reaching the add-on within that;
  - a stream silent for READ_SECONDS is closed. An add-on should send a
    comment line well within it, as the HTML standard advises for the
    same reason: "authors can include a comment line (one starting with
    a ':' character) every 15 seconds or so."

WEBSOCKETS DO NOT PASS, by the owner's plan: they need two runtime
dependencies, and no add-on uses one yet.
"""

import fcntl
import json
import logging
import os
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import IO, Any

import requests

from core.addons import (
    IDENTITY_HEADER,
    command_line,
    new_secret,
    request_headers,
    response_headers,
    sign_identity,
)

logger = logging.getLogger(__name__)

STATE_FILENAME = "server.json"
#: Connecting to a server on this machine is immediate or not at all.
CONNECT_SECONDS = 2.0
#: Longest wait for the next bytes of a response.
READ_SECONDS = 30.0
#: Event streams open at once through one worker.
STREAMS_PER_WORKER = 8
#: Then a stream ends and the browser reconnects (api/live_updates.py).
MAX_STREAM_SECONDS = 600.0
CHUNK_BYTES = 64 * 1024

_streams = threading.BoundedSemaphore(STREAMS_PER_WORKER)
#: One connection pool per worker: requests.Session is safe to share for
#: sending requests, and keeps the loopback connections open.
_session = requests.Session()


def addon_directory(data_dir: Path, module_id: str) -> Path:
    """Where one add-on's server keeps its state, start file and data."""
    return Path(data_dir) / "addons" / module_id


def read_state(data_dir: Path, module_id: str) -> "dict | None":
    """`server.json` as the supervisor last wrote it, or None."""
    try:
        state = json.loads((addon_directory(data_dir, module_id) / STATE_FILENAME).read_text())
    except (OSError, ValueError):
        return None
    return state if isinstance(state, dict) else None


class Unavailable(Exception):
    """The add-on's server cannot answer now; said to the browser as a 503."""


class Upstream:
    """One response from an add-on's server, ready to hand on."""

    def __init__(self, response: requests.Response, streaming: bool) -> None:
        self.status = response.status_code
        self.headers = response_headers(response.headers.items())
        self._response = response
        self._streaming = streaming

    def body(self) -> Iterator[bytes]:
        """The body as it arrives, AS SENT -- not decompressed, since its
        Content-Encoding goes to the browser with it."""
        deadline = time.monotonic() + MAX_STREAM_SECONDS
        try:
            for chunk in self._response.raw.stream(CHUNK_BYTES, decode_content=False):
                yield chunk
                if self._streaming and time.monotonic() > deadline:
                    break
        except (requests.RequestException, OSError) as error:
            # Headers are already sent: all that can be done is to stop.
            logger.warning("an add-on's response broke off: %s", type(error).__name__)
        finally:
            self._response.close()
            if self._streaming:
                _streams.release()


def forward(data_dir: Path, module_id: str, user_id: str, *, method: str, path: str, query: str,
            headers, body: bytes) -> Upstream:
    """Send one request to an add-on's server, as `user_id`; see the
    module docstring. Unavailable when its server is not running, does
    not answer, or too many streams are open."""
    state = read_state(data_dir, module_id)
    if state is None or state.get("state") != "running" or not state.get("url") or not state.get("secret"):
        raise Unavailable(f"the add-on's server is {'not started' if state is None else state.get('state')}")
    outgoing = request_headers(headers)
    outgoing[IDENTITY_HEADER] = sign_identity(state["secret"], audience=module_id, user_id=user_id)
    url = f"{state['url']}/{path}" + (f"?{query}" if query else "")
    try:
        response = _session.request(method, url, headers=outgoing, data=body or None, stream=True,
                                    timeout=(CONNECT_SECONDS, READ_SECONDS), allow_redirects=False)
    except requests.RequestException as error:
        raise Unavailable(f"the add-on's server did not answer ({type(error).__name__})") from None
    streaming = response.headers.get("content-type", "").split(";")[0].strip() == "text/event-stream"
    if streaming and not _streams.acquire(blocking=False):
        response.close()
        raise Unavailable(f"{STREAMS_PER_WORKER} event streams are already open through this worker")
    return Upstream(response, streaming)


# =============================================================================
# THE LIFECYCLE (step 2.2): Elysium starts each add-on's server, watches
# it, restarts it when it fails, and stops it with a deadline. The
# owner's choice, 22 October: Elysium starts it, rather than a person
# starting it beside Elysium.
#
# STARTED with the manifest's command, in the module's folder, its
# output appended to `<log dir>/addons/<id>.log`, and given:
#
#   PORT                  to listen on, on 127.0.0.1 -- Heroku's
#                         convention: "The port to bind to is assigned
#                         by Heroku as the PORT environment variable."
#   ELYSIUM_ADDON_START   a file readable by Elysium's user only: the
#                         port, the token's secret, the options from
#                         addons.yaml, and a data directory of its own
#                         (sdk/python/elysium_addon.py has the shape)
#
# and NOTHING ELSE OF ELYSIUM'S ENVIRONMENT -- which holds every silo's
# ${VAR} credentials -- beyond what a program needs to run at all
# (PATH, HOME, the locale, the time zone). A secret an add-on needs is
# an option, `${VAR}` in addons.yaml, so it reaches only that add-on.
#
# STANDARD INPUT IS A PIPE that closes when Elysium goes, killed or
# not; the add-on leaves when it does (elysium_addon.exit_when_elysium_
# does), so nothing is left running that nobody will stop.
#
# HEALTHY when GET on its `health` path answers 200. "starting" until it
# first does -- for at most START_SECONDS -- then "running", asked every
# HEALTH_EVERY_SECONDS; HEALTH_FAILURES failures in a row, Kubernetes'
# default failureThreshold, and it is restarted.
#
# RESTARTED WITH BACK-OFF when it exits or stops answering: 1 s, then
# doubling, at most 60 s, and back to 1 s once it has run soundly for a
# minute. Kubernetes' shape -- "exponential back-off delay (10s, 20s,
# 40s, ...) that is capped at five minutes, and is reset after ten
# minutes of successful execution" -- at the scale of a server on the
# same machine, where a start takes a second rather than a pull.
#
# STOPPED with SIGTERM to its process group, then SIGKILL after the
# manifest's `stopSeconds`: systemd's order, "first terminated via
# SIGTERM", the request "repeated with the SIGKILL signal" once the
# timeout passes. Its whole group, as systemd's control-group mode: a
# server's own children go with it.
#
# ONE WORKER RUNS EACH SERVER. Several workers each run this loop; each
# add-on's directory holds a `lock` file, and the worker holding its
# flock is the one supervising -- released by the kernel if that worker
# dies, when another takes it over within a round. The same mechanism
# as core/mirror/sync_lock.py, for the same reason: a lock a crash
# cannot leave behind.
#
# FOLLOWS THE CONFIGURATION: each round reads the current generation's
# modules, so a module turned off in the module manager has its server
# stopped, one turned on has it started, and one whose command or
# options changed is restarted with the new ones.
# =============================================================================

START_FILENAME = "start.json"
LOCK_FILENAME = "lock"
RESTART_FILENAME = "restart"
CONTRACT = 1
TICK_SECONDS = 0.5
START_SECONDS = 30.0
HEALTH_EVERY_SECONDS = 5.0
HEALTH_FAILURES = 3
HEALTH_TIMEOUT_SECONDS = 2.0
FIRST_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 60.0
RESET_AFTER_SECONDS = 60.0
#: A log past this is moved to `<id>.log.1` at the next start.
LOG_BYTES = 5 * 1024 * 1024
#: Of Elysium's environment, what an add-on's server is given.
ENVIRONMENT_KEPT = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR")


def _write_private(path: Path, value: dict) -> None:
    """JSON, readable by Elysium's user only, replaced whole: a reader
    sees the old file or the new one, never half of one."""
    partial = path.with_suffix(path.suffix + ".part")
    partial.unlink(missing_ok=True)
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle)
    partial.replace(path)


def _free_port() -> int:
    """A port nothing listens on now. Another program could take it before
    the add-on binds it; the add-on then fails to start, and is started
    again on another."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def log_path(log_dir: Path, module_id: str) -> Path:
    return Path(log_dir) / "addons" / f"{module_id}.log"


def log_tail(log_dir: Path, module_id: str, lines: int = 200) -> list[str]:
    """The end of an add-on's log, for the System page."""
    try:
        with open(log_path(log_dir, module_id), "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 64 * 1024))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return []
    return text.splitlines()[-lines:]


def request_restart(data_dir: Path, module_id: str) -> None:
    """Ask whichever worker supervises it to restart an add-on's server."""
    directory = addon_directory(data_dir, module_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RESTART_FILENAME).touch()


class _Server:
    """One add-on's server, supervised by this worker (it holds the lock)."""

    def __init__(self, module, options: Mapping, data_dir: Path, log_dir: Path, lock: IO) -> None:
        self.module, self.options, self.lock = module, options, lock
        self.directory = addon_directory(data_dir, module.id)
        self.log = log_path(log_dir, module.id)
        self.fingerprint = _fingerprint(module, options)
        self.process: subprocess.Popen | None = None
        self.state = "starting"
        self.since = time.time()
        self.restarts = 0
        self.last_exit: int | None = None
        self.backoff = FIRST_BACKOFF_SECONDS
        #: When it is next started: wall clock for the state file, and
        #: the monotonic clock the rounds compare against.
        self.next_start = 0.0
        self.next_start_monotonic = 0.0
        self.started_at = 0.0
        self.healthy_since: float | None = None
        self.failures = 0
        self.asked_at = 0.0
        self.port = 0
        self.secret = ""

    # -- the state file -----------------------------------------------------

    def _write_state(self) -> None:
        live = self.state in ("starting", "running") and self.process is not None
        _write_private(self.directory / STATE_FILENAME, {
            "state": self.state, "since": self.since, "restarts": self.restarts,
            "lastExit": self.last_exit, "pid": self.process.pid if live and self.process else None,
            "nextStartAt": self.next_start if self.state == "backing-off" else None,
            "url": f"http://127.0.0.1:{self.port}" if live else None,
            "secret": self.secret if live else None,
        })

    def _become(self, state: str) -> None:
        if state != self.state:
            self.state, self.since = state, time.time()
        self._write_state()

    def _say(self, line: str) -> None:
        """A line of Elysium's own in the add-on's log, marked as such."""
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "a", encoding="utf-8") as handle:
            handle.write(f"[elysium {time.strftime('%Y-%m-%d %H:%M:%S')}] {line}\n")

    # -- starting -----------------------------------------------------------

    def spawn(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self.directory / "data").mkdir(exist_ok=True, mode=0o700)
        self.log.parent.mkdir(parents=True, exist_ok=True)
        if self.log.exists() and self.log.stat().st_size > LOG_BYTES:
            self.log.replace(self.log.with_suffix(".log.1"))
        self.port, self.secret = _free_port(), new_secret()
        start = self.directory / START_FILENAME
        _write_private(start, {
            "contract": CONTRACT, "id": self.module.id, "port": self.port,
            "identity": {"header": IDENTITY_HEADER, "secret": self.secret,
                         "issuer": "elysium", "audience": self.module.id},
            "options": _plain(self.options), "dataDir": str(self.directory / "data"),
        })
        environment = {name: os.environ[name] for name in ENVIRONMENT_KEPT if name in os.environ}
        environment.update({"PORT": str(self.port), "ELYSIUM_ADDON_START": str(start)})
        command = command_line(self.module.server, self.module.folder)
        try:
            with open(self.log, "ab") as output:
                self.process = subprocess.Popen(
                    command, cwd=self.module.folder, env=environment, stdin=subprocess.PIPE,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
        except OSError as error:
            # A program that is not there fails like one that exits at
            # once: said in its log, and tried again after the back-off.
            self._say(f"could not start {command[0]}: {error.strerror or error}")
            self.process = None
            self._failed(now=time.monotonic(), status=None)
            return
        self._say(f"started, pid {self.process.pid}, port {self.port}")
        self.started_at, self.asked_at, self.failures, self.healthy_since = time.monotonic(), 0.0, 0, None
        self._become("starting")

    def _failed(self, *, now: float, status: "int | None") -> None:
        self.last_exit = status
        self.restarts += 1
        self.next_start = time.time() + self.backoff
        self.next_start_monotonic = now + self.backoff
        self._say(f"restarting in {self.backoff:g} s")
        self.backoff = min(self.backoff * 2, MAX_BACKOFF_SECONDS)
        self._become("backing-off")

    # -- each round -----------------------------------------------------------

    def tick(self, now: float) -> None:
        restart = self.directory / RESTART_FILENAME
        if restart.exists():
            restart.unlink(missing_ok=True)
            self._say("restart asked for")
            self.stop()
            self.backoff = FIRST_BACKOFF_SECONDS
            self.spawn()
            return
        if self.state == "backing-off":
            if now >= self.next_start_monotonic:
                self.spawn()
            return
        if self.process is None:
            return
        status = self.process.poll()
        if status is not None:
            self._say(f"exited with status {status}")
            self._close_stdin()
            self.process = None
            self._failed(now=now, status=status)
            return
        if self.state == "running" and self.healthy_since is not None \
                and now - self.healthy_since >= RESET_AFTER_SECONDS:
            self.backoff = FIRST_BACKOFF_SECONDS
        wait = TICK_SECONDS if self.state == "starting" else HEALTH_EVERY_SECONDS
        if now - self.asked_at < wait:
            return
        self.asked_at = now
        if self._healthy():
            self.failures = 0
            if self.state == "starting":
                self.healthy_since = now
                self._say("healthy")
                self._become("running")
            return
        if self.state == "starting":
            if now - self.started_at > START_SECONDS:
                self._say(f"not healthy after {START_SECONDS:g} s")
                self._replace(now)
            return
        self.failures += 1
        if self.failures >= HEALTH_FAILURES:
            self._say(f"{HEALTH_FAILURES} health checks failed in a row")
            self._replace(now)

    def _replace(self, now: float) -> None:
        status = self.stop()
        self._failed(now=now, status=status)

    def _healthy(self) -> bool:
        try:
            answer = requests.get(f"http://127.0.0.1:{self.port}{self.module.server.health}",
                                  timeout=HEALTH_TIMEOUT_SECONDS, allow_redirects=False)
            answer.close()
            return answer.status_code == 200
        except requests.RequestException:
            return False

    # -- stopping -----------------------------------------------------------

    def terminate(self) -> None:
        """SIGTERM to the whole group, without waiting."""
        if self.process is not None and self.process.poll() is None:
            self._signal(signal.SIGTERM)

    def _signal(self, which: int) -> None:
        try:
            os.killpg(self.process.pid, which)  # type: ignore[union-attr]
        except (ProcessLookupError, PermissionError):
            pass

    def _close_stdin(self) -> None:
        if self.process is not None and self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass

    def stop(self, deadline: "float | None" = None) -> "int | None":
        """SIGTERM, then SIGKILL at the deadline (default: stopSeconds from
        now). The exit status, or None if it was not running."""
        if self.process is None:
            return None
        self._become("stopping")
        self.terminate()
        until = deadline if deadline is not None else time.monotonic() + self.module.server.stop_seconds
        try:
            status = self.process.wait(timeout=max(0.0, until - time.monotonic()))
        except subprocess.TimeoutExpired:
            self._say(f"still running {self.module.server.stop_seconds:g} s after SIGTERM; SIGKILL")
            self._signal(signal.SIGKILL)
            status = self.process.wait()
        else:
            # ITS GROUP TOO: a child it started, and left, goes with it.
            self._signal(signal.SIGKILL)
        self._close_stdin()
        self._say(f"stopped, status {status}")
        self.process = None
        return status

    def retire(self) -> None:
        """No longer this worker's: stopped, the state file says so, and
        the lock is let go for whoever wants it."""
        self.stop()
        self._become("stopped")
        self.lock.close()


def _fingerprint(module, options: Mapping) -> str:
    """What the server was started from: a change restarts it."""
    spec = module.server
    return json.dumps([str(module.folder), list(spec.command), spec.health, spec.stop_seconds,
                       _plain(options)], sort_keys=True, default=str)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _take_lock(directory: Path) -> "IO | None":
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = open(directory / LOCK_FILENAME, "a+")  # noqa: SIM115 -- held for as long as it supervises
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


#: What the supervisor should be running: (module, options) for each
#: module turned on that declares a server.
Wanted = Callable[[], "list[tuple[Any, Mapping]]"]


def wanted_from(modules) -> "list[tuple[Any, Mapping]]":
    """The modules of a configuration with a server, and their options."""
    if modules is None:
        return []
    return [(m, modules.addon_options.get(m.id, {})) for m in modules.modules if m.server is not None]


class Supervisor:
    """Runs the add-on servers this worker holds the lock for; see above."""

    def __init__(self, data_dir: Path, log_dir: Path, wanted: Wanted) -> None:
        self.data_dir, self.log_dir, self._wanted = Path(data_dir), Path(log_dir), wanted
        self._servers: dict[str, _Server] = {}
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="addon-supervisor", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stopping.is_set():
            try:
                self.round()
            except Exception:  # noqa: BLE001 -- the loop must outlive one bad round
                logger.exception("supervising add-on servers")
            self._stopping.wait(TICK_SECONDS)

    def round(self) -> None:
        """One look at what should run and what is: public for the tests."""
        wanted = {m.id: (m, options) for m, options in self._wanted()}
        for module_id in list(self._servers):
            server = self._servers[module_id]
            if module_id not in wanted or _fingerprint(*wanted[module_id]) != server.fingerprint:
                server._say("its module was turned off or changed")
                server.retire()
                del self._servers[module_id]
        for module_id, (module, options) in wanted.items():
            if module_id in self._servers:
                continue
            lock = _take_lock(addon_directory(self.data_dir, module_id))
            if lock is None:
                continue  # another worker supervises it
            server = _Server(module, options, self.data_dir, self.log_dir, lock)
            self._servers[module_id] = server
            server.spawn()
        now = time.monotonic()
        for server in list(self._servers.values()):
            server.tick(now)

    def close(self) -> None:
        """Stop every server this worker runs: all told at once, each given
        its own stopSeconds, so shutting down takes the longest of them,
        not their sum."""
        self._stopping.set()
        if self._thread.is_alive():
            self._thread.join()
        servers = list(self._servers.values())
        for server in servers:
            server.terminate()
        now = time.monotonic()
        for server in servers:
            server.stop(deadline=now + server.module.server.stop_seconds)
            server._become("stopped")
            server.lock.close()
        self._servers.clear()
