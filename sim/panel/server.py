"""
server.py  (the simulator's control panel, as an Elysium add-on's server)

BLOCKING.md item 3, step 2.3, and item 11's "control panel served by the
simulator itself". Elysium starts this (its module.json's `server`) and
forwards the panel page's calls to it; this, in turn, operates a world
through the channel the simulator already has (simulator/control.py).

THE WORLD IS NOT THIS SERVER'S CHILD IN ANY WAY THAT MATTERS. The
owner, 22 October: Elysium "should be able to be probed as if it went
offline while the remote resources continued on their functioning per
normal". So:

  - Start runs `simulator run --follow` as a process of its own, in a
    session of its own: Elysium stopping this server -- SIGTERM to its
    process group, then SIGKILL -- does not reach the world, and neither
    does this server's standard input closing when Elysium goes.
  - This server keeps nothing about the world in memory. Every request
    finds it again through `control.json` in its directory, so a server
    started after Elysium comes back sees the world that ran on without
    it.
  - The world stops only when asked: Stop here, `simulator stop` in a
    terminal, or SIGTERM to it, each through the run's own teardown.

WHAT IT DOES NOT DO is import Elysium. elysium_addon.py beside this is a
copy of sdk/python/elysium_addon.py -- the copy add-ons are meant to
carry -- and Elysium's tests check the two are the same file.

THE DEPLOYMENT'S OPTIONS (addons.yaml, `simulator: options:`):

    directory   where the world lives (default: a `world` folder in the
                data directory Elysium gives this server)
    packs       the folder of pack files offered (default: sim/packs)

Every call but /health needs a signed-in person (X-Elysium-Identity), and
everything that changes the world needs the module's declared permission
`operate` -- which Elysium already requires to reach the panel at all; it
is checked here again because this server must not take a proxy's word
for what a token does not say.
"""

import json
import os
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parent
sys.path.insert(0, str(SIM))
sys.path.insert(0, str(HERE))

import elysium_addon  # noqa: E402 -- beside this file, as an add-on carries it
from simulator.attaching import CONNECTIONS_FILENAME  # noqa: E402
from simulator.control import CONTROL_FILENAME, ControlError, WorldBusy, run_under_way, send  # noqa: E402
from simulator.resume import existing_world  # noqa: E402

#: How long the page waits on the world before saying it is busy.
ASK_SECONDS = 4.0
#: Commands the page may send, and the arguments each takes.
COMMANDS = {"pause": (), "resume": (), "advance": ("duration",), "speed": ("compression",),
            "outage": ("silo",), "restore": ("silo",)}
LOG_FILENAME = "run.log"


class Panel:
    """What the routes below do, apart from HTTP."""

    def __init__(self, info: dict) -> None:
        options = info.get("options") or {}
        data = Path(info.get("dataDir") or HERE / "var")
        self.directory = Path(options.get("directory") or data / "world").expanduser()
        self.packs = Path(options.get("packs") or SIM / "packs").expanduser()
        self.log = self.directory.parent / f"{self.directory.name}-{LOG_FILENAME}"
        #: The `simulator run` this server started, while it is starting:
        #: None once the world answers, or if another started it.
        self._launched: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # -- reading ----------------------------------------------------------

    def packs_offered(self) -> list[dict]:
        found = []
        for path in sorted(self.packs.glob("*.yaml")):
            description = ""
            try:
                for line in path.read_text().splitlines():
                    if line.startswith("description:"):
                        description = line.partition(":")[2].strip().strip("\"'")
                        break
            except OSError:
                continue
            found.append({"name": path.stem, "description": description})
        return found

    def state(self) -> dict:
        """The world as it is now: found again each time (see above)."""
        # A RUN UNDER WAY holds the directory's run lock from its first
        # moment to its last, tidying up included (simulator/control.py);
        # one this server just launched may not have taken it yet.
        under_way = run_under_way(self.directory) or self._still_launching()
        world, problem, busy = None, None, False
        if (self.directory / CONTROL_FILENAME).exists():
            try:
                world = send(self.directory, "status", reply_timeout=ASK_SECONDS)
            except WorldBusy:
                busy = True
            except ControlError as error:
                problem = str(error)
        if world is not None:
            phase = "running"
        elif busy or under_way:
            # Building, catching up on its first days, or tidying up.
            phase = "busy"
        elif problem is not None:
            # control.json left behind by a run that ended without tidying
            # up: discarding cleans up whatever it left running.
            phase = "not answering"
        else:
            phase = "stopped"
        return {
            "phase": phase,
            "world": world,
            "problem": problem,
            "directory": str(self.directory),
            "resumable": existing_world(self.directory),
            # THE PACK IT WAS BUILT FROM, which a resume must be given
            # again: connections.json names it, and outlives the run.
            "pack": (self._connections() or {}).get("pack"),
            "packs": self.packs_offered(),
            "connections": self._connections() if phase == "running" else None,
        }

    def _connections(self) -> "dict | None":
        try:
            return json.loads((self.directory / CONNECTIONS_FILENAME).read_text())
        except (OSError, ValueError):
            return None

    def _still_launching(self) -> bool:
        with self._lock:
            if self._launched is None:
                return False
            if self._launched.poll() is not None:
                self._launched = None
                return False
            return True

    def log_tail(self, lines: int = 200) -> list[str]:
        try:
            with open(self.log, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                handle.seek(max(0, handle.tell() - 64 * 1024))
                return handle.read().decode("utf-8", "replace").splitlines()[-lines:]
        except OSError:
            return []

    # -- changing ---------------------------------------------------------

    def start(self, body: dict) -> dict:
        current = self.state()
        if current["phase"] in ("running", "busy"):
            raise ControlError(f"a world is already {current['phase']} in {self.directory}")
        resume = bool(body.get("resume"))
        if resume and not current["resumable"]:
            raise ControlError(f"there is no world to resume in {self.directory}")
        if not resume and current["resumable"]:
            raise ControlError(f"a stopped world is in {self.directory}; resume it, or discard it first")
        pack = str(body.get("pack", ""))
        if resume and current["pack"] is not None and pack != current["pack"]:
            raise ControlError(f"the world here was built from {current['pack']}, not {pack}")
        if pack not in {p["name"] for p in current["packs"]}:
            raise ControlError(f"no pack {pack!r}; there are {[p['name'] for p in current['packs']]}")
        try:
            days = float(body.get("days", 7))
            compression = float(body.get("compression", 60))
        except (TypeError, ValueError):
            raise ControlError("days and compression must be numbers") from None
        if not 0 <= days <= 366 or not 0 < compression <= 1_000_000:
            raise ControlError("days must be 0 to 366, and compression more than 0")
        command = [sys.executable, "-m", "simulator", "run", str(self.packs / f"{pack}.yaml"),
                   "--dir", str(self.directory), "--follow", "--compression", f"{compression:g}",
                   "--days", f"{0 if resume else days:g}"]
        if resume:
            command.append("--resume")
        self.directory.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "ab") as output, self._lock:
            # ITS OWN SESSION, AND NOT OUR STANDARD INPUT: neither Elysium
            # stopping this server nor Elysium going away reaches it.
            self._launched = subprocess.Popen(
                command, cwd=SIM, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True,
                # UNBUFFERED, or its log reads "nothing yet" until it stops:
                # a Python writing to a file holds its output in blocks.
                env={**os.environ, "PYTHONUNBUFFERED": "1"})
        return {"started": True, "pid": self._launched.pid}

    def stop(self) -> dict:
        try:
            return send(self.directory, "stop", reply_timeout=ASK_SECONDS)
        except WorldBusy:
            # STILL BUILDING, so nothing serves its queue: SIGTERM does
            # the same, through the same teardown (simulator/cli.py).
            pid = self._pid()
            if pid is None:
                raise
            os.kill(pid, signal.SIGTERM)
            return {"stopping": True}

    def _pid(self) -> "int | None":
        try:
            return int(json.loads((self.directory / CONTROL_FILENAME).read_text())["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            with self._lock:
                return None if self._launched is None else self._launched.pid

    def command(self, body: dict) -> dict:
        name = str(body.get("command", ""))
        if name not in COMMANDS:
            raise ControlError(f"no command {name!r} here; there are {sorted(COMMANDS)}")
        arguments = {key: body[key] for key in COMMANDS[name] if key in body}
        return send(self.directory, name, reply_timeout=ASK_SECONDS * 4, **arguments)

    def discard(self) -> dict:
        """The stopped world and its directory, so a different pack can be
        started. Refused while anything is running there."""
        if self.state()["phase"] in ("running", "busy"):
            raise ControlError("stop the world, and let it finish tidying up, before discarding it")
        result = subprocess.run([sys.executable, "-m", "simulator", "clean", "--dir", str(self.directory),
                                 "--remove"], cwd=SIM, capture_output=True, text=True, timeout=120,
                                stdin=subprocess.DEVNULL)
        if result.returncode != 0 or self.directory.exists():
            raise ControlError((result.stderr or result.stdout).strip() or "could not discard it")
        return {"discarded": True}


def make_server(info: dict, port: int = 0) -> ThreadingHTTPServer:
    panel = Panel(info)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args) -> None:
            pass

        def _reply(self, status: int, value) -> None:
            body = json.dumps(value, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _who(self) -> "dict | None":
            try:
                return elysium_addon.identity(self.headers, info)
            except elysium_addon.NotSignedIn as refused:
                self._reply(401, {"detail": str(refused)})
                return None

        def do_GET(self) -> None:  # noqa: N802 -- http.server's naming
            if self.path == "/health":
                return self._reply(200, {"ok": True})
            who = self._who()
            if who is None:
                return None
            if self.path == "/state":
                return self._reply(200, {**panel.state(), "may_operate": elysium_addon.holds(who, "operate")})
            if self.path == "/log":
                return self._reply(200, {"lines": panel.log_tail()})
            return self._reply(404, {"detail": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            who = self._who()
            if who is None:
                return None
            if not elysium_addon.holds(who, "operate"):
                return self._reply(403, {"detail": "Needs module:simulator:operate"})
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._reply(400, {"detail": "the body must be a JSON object"})
            actions = {"/start": panel.start, "/stop": lambda _b: panel.stop(),
                       "/command": panel.command, "/discard": lambda _b: panel.discard()}
            action = actions.get(self.path)
            if action is None:
                return self._reply(404, {"detail": "Not found"})
            try:
                return self._reply(200, action(body))
            except ControlError as refused:
                return self._reply(409, {"detail": str(refused)})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    info = elysium_addon.start()
    server = make_server(info, int(os.environ["PORT"]))
    # STOPPING THIS SERVER STOPS ONLY THIS SERVER. The world runs on.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    elysium_addon.exit_when_elysium_does()
    print(f"simulator panel listening on {server.server_address[1]}, world in {Panel(info).directory}",
          flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
