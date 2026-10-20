"""Operating a running world from outside it (REAL_SOURCES.md O1-O3, O5).

A world runs in one process; an operator -- a person at a terminal, or
the control panel BLOCKING.md asks for -- is somewhere else. Until this,
the only contact was the databases, which is right for CONSUMERS and
wrong for the OPERATOR: `simulator drift` from another terminal changed
the database behind the running engine's back and the engine crashed on
its next write; and there was no way to pause, take a source down, or
read the oracle from outside.

The consumer's rule is unchanged. This is not a consumer interface and
appears nowhere a consumer looks: its address and token are in
`control.json` beside the world, readable by the owner only, never in
`connections.json`. Consumers still have only the databases.

One thread does the work. The HTTP server's threads only queue commands
and wait; the loop that runs the world carries them out between ticks
(`serve`), so the engine's model, its connections and its transactions
stay single-threaded, as they always were.

Commands (POST /control, {"command": ..., ...}, bearer token):

  status                        clock, pause, each silo up/down/out
  pause / resume                stop and restart simulated time
  advance {"duration": "3d"}    run time forward now, paused or not
  drift {"operation", fields}   a schema change, applied by the engine
                                itself, so its model moves with it
  outage {"silo"} / restore     cut a silo off from its reader, and back
                                (simulator/outages.py)
  oracle                        every watched number's samples, as JSON
"""

import json
import os
import queue
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import Future
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from simulator import outages, runner

CONTROL_FILENAME = "control.json"
#: How long a request waits for the world to reach a moment between ticks.
#: A long backfill runs before the loop serves anything; the request is
#: then told the world is busy rather than left hanging.
REPLY_TIMEOUT_SECONDS = 120.0


class ControlError(Exception):
    """A command that cannot be carried out, said in its own words."""


def apply_drift(world, operation: str, fields: dict[str, Any]):
    """A schema change applied by the engine: the database and the world's
    own model move together, and the oracle samples the moment. Shared by
    the console and the control server, so the two say the same words."""
    from simulator.spec import PackError, build_change

    if "table" not in fields:
        raise ControlError("drift needs table=silo.table")
    silo_name = str(fields["table"]).split(".")[0]
    if silo_name not in world.schemas:
        raise ControlError(f"no silo {silo_name!r} holds a schema in this world")
    try:
        change = build_change(operation, fields, world.schema(silo_name))
    except (PackError, KeyError) as error:
        raise ControlError(str(error)) from error
    world.apply_change(silo_name, change)
    world.oracle.sample(world)
    return change


class Controller:
    """The world's side: a queue, and what each command does."""

    def __init__(self, world) -> None:
        self.world = world
        self.paused = False
        self.out: set[str] = set()
        self._queue: queue.Queue[tuple[str, dict, Future]] = queue.Queue()

    # -- the HTTP side ----------------------------------------------------

    def submit(self, command: str, arguments: dict) -> Any:
        future: Future = Future()
        self._queue.put((command, arguments, future))
        try:
            return future.result(timeout=REPLY_TIMEOUT_SECONDS)
        except TimeoutError as error:
            # Withdrawn, not left queued: a command reported as failed
            # must not then happen anyway, or a retry does it twice.
            # cancel() fails only if the world has already started it.
            if future.cancel():
                raise ControlError("the world is busy (a backfill or a long tick) and did "
                                   "not get to this; nothing was done. Try again shortly"
                                   ) from error
            raise ControlError("the world started this but has not finished it; check "
                               "`status` before trying again") from error

    # -- the world's side ---------------------------------------------------

    def serve(self) -> None:
        """Carry out every queued command. Called by the loop running the
        world, between ticks, on its own thread."""
        while True:
            try:
                command, arguments, future = self._queue.get_nowait()
            except queue.Empty:
                return
            if not future.set_running_or_notify_cancel():
                continue        # withdrawn by a caller that stopped waiting
            try:
                future.set_result(self._do(command, arguments))
            except Exception as error:  # noqa: BLE001 - every failure goes back to the caller
                future.set_exception(error)

    def _do(self, command: str, arguments: dict) -> Any:
        # Named here rather than found by name, so the list of what an
        # operator can do is one place a reader can see.
        handlers: dict[str, Callable[[dict], Any]] = {
            "status": self._cmd_status, "pause": self._cmd_pause,
            "resume": self._cmd_resume, "advance": self._cmd_advance,
            "drift": self._cmd_drift, "outage": self._cmd_outage,
            "restore": self._cmd_restore, "oracle": self._cmd_oracle,
        }
        handler = handlers.get(command)
        if handler is None:
            raise ControlError(f"no command {command!r}; known: {sorted(handlers)}")
        return handler(arguments)

    def _silo(self, arguments: dict):
        name = arguments.get("silo")
        if name not in self.world.silos:
            raise ControlError(f"no silo {name!r}; this world has {sorted(self.world.silos)}")
        return name, self.world.silo(name)

    def _cmd_status(self, _arguments: dict) -> dict:
        world = self.world
        return {
            "pack": world.pack.name,
            "clock": world.clock.now().isoformat(),
            "elapsed_days": round(world.clock.elapsed.total_seconds() / 86400, 3),
            "paused": self.paused,
            "silos": {name: {"kind": silo.kind,
                             "state": "out" if name in self.out
                             else ("up" if silo.is_reachable() else "down")}
                      for name, silo in sorted(world.silos.items())},
        }

    def _cmd_pause(self, _arguments: dict) -> dict:
        self.paused = True
        return {"paused": True, "clock": self.world.clock.now().isoformat()}

    def _cmd_resume(self, _arguments: dict) -> dict:
        self.paused = False
        return {"paused": False, "clock": self.world.clock.now().isoformat()}

    def _cmd_advance(self, arguments: dict) -> dict:
        from simulator.spec.values import _duration

        seconds = _duration(str(arguments.get("duration", "")), "advance")
        written = runner.run(self.world, total_seconds=seconds, tick_seconds=3600)
        return {"clock": self.world.clock.now().isoformat(), "rows_written": written}

    def _cmd_drift(self, arguments: dict) -> dict:
        fields = dict(arguments)
        operation = str(fields.pop("operation", ""))
        if not operation:
            raise ControlError("drift needs an operation, as in drop_column")
        change = apply_drift(self.world, operation, fields)
        return {"applied": change.describe(), "breaking": change.is_breaking}

    def _cmd_outage(self, arguments: dict) -> dict:
        name, silo = self._silo(arguments)
        # Noted first, so an interruption part-way still restores it.
        self.out.add(name)
        did = outages.cut_off(silo, self.world.pack.silos[name].database)
        return {"silo": name, "out": True, "did": did}

    def _cmd_restore(self, arguments: dict) -> dict:
        name, silo = self._silo(arguments)
        did = outages.restore(silo, self.world.pack.silos[name].database)
        self.out.discard(name)
        return {"silo": name, "out": False, "did": did}

    def _cmd_oracle(self, _arguments: dict) -> dict:
        oracle = self.world.oracle
        return {watch.name: [{"at": sample.at.isoformat(),
                              "value": None if sample.value is None else str(sample.value),
                              "ok": sample.ok}
                             for sample in oracle.series.get(watch.name, [])]
                for watch in oracle.watches}

    def restore_everything(self) -> None:
        """Before the world stops: an outage must not outlive it, or the
        next run starts with a reader locked out and a share moved aside."""
        for name in sorted(self.out):
            try:
                outages.restore(self.world.silo(name), self.world.pack.silos[name].database)
            except Exception:  # noqa: BLE001 - stopping goes on regardless
                pass
        self.out.clear()


class ControlServer:
    """Loopback HTTP, a bearer token, and control.json for the operator."""

    def __init__(self, controller: Controller, directory: Path) -> None:
        self.controller = controller
        self.path = Path(directory) / CONTROL_FILENAME
        self.token = secrets.token_urlsafe(24)
        controller_ref, token = controller, self.token

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802 -- http.server's naming
                if self.headers.get("Authorization") != f"Bearer {token}":
                    return self._reply(401, {"error": "a bearer token from control.json is needed"})
                if self.path != "/control":
                    return self._reply(404, {"error": "POST /control"})
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                    command = str(body.pop("command", ""))
                    return self._reply(200, {"ok": True, "result":
                                             controller_ref.submit(command, body)})
                except Exception as error:  # noqa: BLE001 - said back, not raised
                    return self._reply(400, {"ok": False, "error": str(error)})

            def _reply(self, status: int, body: dict) -> None:
                payload = json.dumps(body, default=_jsonable).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        name="control", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def start(self) -> None:
        self._thread.start()
        partial = self.path.with_suffix(".json.part")
        # A leftover keeps its old permissions; O_CREAT's mode applies
        # only to a file it creates.
        partial.unlink(missing_ok=True)
        # Readable by the owner only: the token commands the world.
        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            json.dump({"url": self.url, "token": self.token, "pid": os.getpid()}, handle)
        partial.replace(self.path)

    def stop(self) -> None:
        self.path.unlink(missing_ok=True)
        self._server.shutdown()
        self._server.server_close()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def send(directory: Path, command: str, **arguments: Any) -> dict:
    """The operator's side: one command to the world running in
    `directory`. ControlError if none is running or the command fails."""
    import urllib.error
    import urllib.request

    path = Path(directory) / CONTROL_FILENAME
    if not path.exists():
        raise ControlError(f"no world is running in {directory} (no {CONTROL_FILENAME})")
    found = json.loads(path.read_text())
    request = urllib.request.Request(
        f"{found['url']}/control", method="POST",
        data=json.dumps({"command": command, **arguments}).encode(),
        headers={"Authorization": f"Bearer {found['token']}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=REPLY_TIMEOUT_SECONDS + 5) as response:
            return json.loads(response.read())["result"]
    except urllib.error.HTTPError as error:
        raise ControlError(json.loads(error.read() or b"{}").get("error", str(error))) from error
    except OSError as error:
        raise ControlError(f"the world in {directory} is not answering ({error}); if it "
                           f"stopped uncleanly, remove {CONTROL_FILENAME}") from error

# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section
# whenever something genuinely open, deferred, or rejected comes up here.
# =============================================================================
#
# RESOLVED (20 October, review): a command whose caller timed out stayed
# queued and ran later, so a retry did it twice. submit() now cancels the
# future on timeout and serve() skips cancelled ones.
#
# DEFERRED: nothing serves the queue during seeding or a `--days` backfill,
# because runner.run() knows nothing of the controller. A command sent then
# times out and is withdrawn, and says so. Serving between backfill ticks
# would mean passing the controller into the runner; worth it if an operator
# ever needs to act mid-backfill.
#
# REJECTED: finding handlers by name (getattr "_cmd_" + command). Vulture
# could not see them, and the table in _do is the list a reader wants.
