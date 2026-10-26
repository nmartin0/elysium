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
import time
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
            "outage": ("silo",), "restore": ("silo",),
            # A schema change, in the pack's own words (sim/simulator/spec/
            # migrations.py): the world's builder checks each field, and
            # its refusal comes back as the page's.
            "drift": ("operation", "table", "column", "to", "type", "length", "precision",
                      "scale", "nullable", "factor", "columns")}
LOG_FILENAME = "run.log"
#: What the watcher last saw, and that a stop was asked for.
WATCHED_FILENAME = "watched.json"
STOP_ASKED_FILENAME = "stop-asked"
#: How often the watcher looks.
WATCH_SECONDS = 5.0


class Panel:
    """What the routes below do, apart from HTTP."""

    def __init__(self, info: dict) -> None:
        options = info.get("options") or {}
        data = Path(info.get("dataDir") or HERE / "var")
        self.directory = Path(options.get("directory") or data / "world").expanduser()
        self.packs = Path(options.get("packs") or SIM / "packs").expanduser()
        self.log = self.directory.parent / f"{self.directory.name}-{LOG_FILENAME}"
        #: Where the watcher keeps what it last saw (Watcher).
        self.data = data
        self.stop_marker = data / STOP_ASKED_FILENAME
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
        # SAID ON DISK, not in memory, so a watcher in a panel started
        # after Elysium restarts still knows this stop was asked for.
        self.stop_marker.parent.mkdir(parents=True, exist_ok=True)
        self.stop_marker.touch()
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

    def schema(self) -> dict:
        """What a schema change may reach, read from the running world."""
        return send(self.directory, "schema", reply_timeout=ASK_SECONDS * 4)

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


class Watcher:
    """TELLS WHOEVER MAY OPERATE THE WORLD what they would want to know
    without having the panel open (BLOCKING.md item 3, step 2.4; the
    owner's choice, 23 October): through Elysium's Inbox, by a file in
    the outbox Elysium gave this server (elysium_addon.post), so a notice
    written while Elysium is offline arrives when it is back.

      ready        it finished building, or resuming, and is running
      crashed      it was running and stopped without tidying up
      not started  it was building and stopped without ever running,
                   and nobody asked it to

    A STOP SOMEONE ASKED FOR SAYS NOTHING: they know. WHAT IT LAST SAW
    IS ON DISK, so a crash while Elysium -- and so this server -- was
    down is still told when it is back: the world was running, and now
    is not answering."""

    def __init__(self, panel: Panel, info: dict) -> None:
        self.panel, self.info = panel, info
        self.path = panel.data / WATCHED_FILENAME

    def _last(self) -> "dict | None":
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None

    def check(self) -> "str | None":
        """One look; the notice posted, by its kind, or None."""
        state = self.panel.state()
        phase, last = state["phase"], self._last()
        world = state["world"] or {}
        pack = world.get("pack") or state.get("pack") or (last or {}).get("pack") or "the world"
        ran = phase == "running" or bool(last and last.get("ran") and phase == "busy")
        posted = None
        if last is not None and last["phase"] != phase:
            asked = self.panel.stop_marker.exists()
            # FROM STOPPED TOO: a world that builds in less than one look
            # is never seen busy (found in a full run, 23 October).
            if phase == "running" and last["phase"] in ("busy", "stopped"):
                posted = self._post("ready", f"The simulated world ({pack}) is running",
                                    f"In {self.panel.directory}.")
            elif phase == "not answering" and last["phase"] in ("running", "busy"):
                posted = self._post("crashed", f"The simulated world ({pack}) stopped without tidying up",
                                    "Its databases may still be running. Discard it from the Simulator "
                                    "page to clean up, then start or resume another.")
            elif phase == "stopped" and last["phase"] == "busy" and not last.get("ran") and not asked:
                posted = self._post("not-started", f"The simulated world ({pack}) did not start",
                                    "It stopped while building. Its log, on the Simulator page, says why.")
        if phase == "stopped":
            self.panel.stop_marker.unlink(missing_ok=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"phase": phase, "pack": pack, "ran": ran}))
        return posted

    def _post(self, kind: str, summary: str, detail: str) -> str:
        elysium_addon.post(self.info, summary, detail=detail, name=f"{kind}-{time.time_ns()}")
        return kind

    def run(self) -> None:
        while True:
            try:
                self.check()
            except Exception as error:  # noqa: BLE001 -- watching outlives one bad look
                print(f"watcher: {error}", flush=True)
            time.sleep(WATCH_SECONDS)


def make_server(info: dict, port: int = 0, shared: "Panel | None" = None) -> ThreadingHTTPServer:
    panel = shared if shared is not None else Panel(info)

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
            if self.path == "/schema":
                try:
                    return self._reply(200, panel.schema())
                except ControlError as refused:
                    return self._reply(409, {"detail": str(refused)})
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
    panel = Panel(info)
    server = make_server(info, int(os.environ["PORT"]), panel)
    if info.get("outbox"):
        threading.Thread(target=Watcher(panel, info).run, name="watcher", daemon=True).start()
    # STOPPING THIS SERVER STOPS ONLY THIS SERVER. The world runs on.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    elysium_addon.exit_when_elysium_does()
    print(f"simulator panel listening on {server.server_address[1]}, world in {panel.directory}",
          flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
