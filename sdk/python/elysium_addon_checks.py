"""
elysium_addon_checks.py  (the checks Elysium's add-on contract makes of an
add-on's server, for the add-on's own tests)

BLOCKING.md item 3, step 2: "Elysium ships a pytest plugin of its
HTTP-contract checks (health, stop within the deadline, honouring the
identity header) that an add-on runs against its own server in its own
repository." COPY THIS FILE BESIDE elysium_addon.py, and in your tests:

    from pathlib import Path
    from elysium_addon_checks import AddonContract

    class TestMyAddonKeepsTheContract(AddonContract):
        manifest = Path(__file__).parent.parent / "module.json"
        protected = ["/state"]          # paths that need a signed-in person
        options = {"directory": "..."}  # what addons.yaml would give it

Each check starts your server THE WAY ELYSIUM DOES (api/addon_servers.py):
the manifest's command in the module's folder, `PORT`, a start file in
`ELYSIUM_ADDON_START`, a bare environment, standard input a pipe, a
process group of its own -- and says, in its own words, what Elysium
would see go wrong:

  health        GET on the manifest's health path answers 200 within
                START_SECONDS
  identity      a protected path refuses no token, a token signed with
                another secret, one made for another add-on and an
                expired one -- and does NOT refuse a good one, or the
                check would pass a server that refuses everybody
  loopback      it listens on 127.0.0.1 only: the proxy is the only way
                in, and the identity token the only word on who is asking
  stop          SIGTERM to its process group, as Elysium sends it, ends
                it within the manifest's stopSeconds, with status 0
  stdin         standard input closing -- Elysium gone, even killed --
                ends it within the same deadline

A MIXIN, NOT A HOOK PLUGIN, deliberately: an add-on's tests choose the
manifest, the paths and the options, and a test class is where pytest
already lets a project say those things -- the shape of a shared
"behaves like" suite (RSpec's `it_behaves_like`), which a class it
subclasses is in pytest.

Standard library and pytest only. Elysium's own tests run every check
against a deliberately broken add-on, one way of breaking per check, so
a check that cannot fail is found (tests/integration/test_addon_checks.py).
"""

import base64
import hashlib
import hmac
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

#: As Elysium waits for a first healthy answer.
START_SECONDS = 30.0
#: Of Elysium's environment, what an add-on is given (api/addon_servers.py).
ENVIRONMENT_KEPT = ("PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TMPDIR")
SECRET = "contract-check-secret-contract-check-secret"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_token(secret: str, audience: str, user: str = "contract-checker", *, issued: "float | None" = None,
               permissions: "list[str] | None" = None) -> str:
    """A token as Elysium's proxy makes it (core/addons.sign_identity)."""
    now = int(time.time() if issued is None else issued)
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = {"iss": "elysium", "aud": audience, "sub": user, "name": user, "iat": now, "exp": now + 60,
              "permissions": permissions or []}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    signature = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(signature)}"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _this_machine_elsewhere() -> "str | None":
    """An address of this machine that is not loopback, or None."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            address = probe.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("127.") else address


class Running:
    """One run of the add-on's server, started as Elysium starts it."""

    def __init__(self, manifest: Path, options: dict, work: Path) -> None:
        spec = json.loads(Path(manifest).read_text())
        self.id = spec["id"]
        server = spec["server"]
        self.health = server.get("health", "/health")
        self.stop_seconds = float(server.get("stopSeconds", 10))
        folder = Path(manifest).resolve().parent
        command = list(server["command"])
        if command[0] == "{python}":
            command[0] = sys.executable
        elif command[0].startswith("./"):
            command[0] = str(folder / command[0][2:])
        self.port = _free_port()
        outbox, data = work / "outbox", work / "data"
        outbox.mkdir(parents=True, exist_ok=True)
        data.mkdir(parents=True, exist_ok=True)
        start = work / "start.json"
        start.write_text(json.dumps({
            "contract": 1, "id": self.id, "port": self.port,
            "identity": {"header": "X-Elysium-Identity", "secret": SECRET, "issuer": "elysium",
                         "audience": self.id},
            "options": options, "dataDir": str(data), "outbox": str(outbox)}))
        os.chmod(start, 0o600)
        environment = {name: os.environ[name] for name in ENVIRONMENT_KEPT if name in os.environ}
        environment.update({"PORT": str(self.port), "ELYSIUM_ADDON_START": str(start)})
        self.log = open(work / "server.log", "ab")  # noqa: SIM115 -- closed in stop()
        self.process = subprocess.Popen(command, cwd=folder, env=environment, stdin=subprocess.PIPE,
                                        stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True)
        self.work = work

    def url(self, path: str, host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}{path}"

    def get(self, path: str, token: "str | None" = None, host: str = "127.0.0.1") -> int:
        """The status a GET answers with; 0 when nothing answers."""
        headers = {} if token is None else {"X-Elysium-Identity": token}
        request = urllib.request.Request(self.url(path, host), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code
        except OSError:
            return 0

    def until_healthy(self, seconds: float = START_SECONDS) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                return False
            if self.get(self.health) == 200:
                return True
            time.sleep(0.2)
        return False

    def ended_within(self, seconds: float) -> "int | None":
        """Its exit status if it ended within `seconds`, else None."""
        try:
            return self.process.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            return None

    def said(self) -> str:
        self.log.flush()
        return (self.work / "server.log").read_text(errors="replace")[-2000:]

    def stop(self) -> None:
        """However the check ended: nothing of it left running."""
        if self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self.process.wait()
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        self.log.close()


class AddonContract:
    """Subclass in your tests; see the module docstring."""

    #: The add-on's module.json.
    manifest: Path
    #: Paths that need a signed-in person: each is asked without a token,
    #: with bad ones, and with a good one.
    protected: "list[str]" = []
    #: What the deployment's addons.yaml would give it.
    options: dict = {}
    #: The add-on's own permissions a good token says the person holds.
    permissions: "list[str]" = []
    #: How long it has to answer its health check: Elysium's limit.
    start_seconds: float = START_SECONDS

    @pytest.fixture
    def addon(self):
        with tempfile.TemporaryDirectory(prefix="addon-contract-") as work:
            running = Running(self.manifest, self.options, Path(work))
            try:
                yield running
            finally:
                running.stop()

    def test_health_answers_200_once_started(self, addon):
        assert addon.until_healthy(self.start_seconds), (
            f"GET {addon.health} did not answer 200 within {self.start_seconds:g} s of starting; Elysium "
            f"would restart it, again and again. Its output:\n{addon.said()}")

    def test_a_protected_path_refuses_who_it_cannot_verify_and_takes_who_it_can(self, addon):
        assert addon.until_healthy(self.start_seconds), addon.said()
        assert self.protected, "name at least one protected path, or this check proves nothing"
        good = make_token(SECRET, addon.id, permissions=self.permissions)
        refused = {"no token": None,
                   "a token signed with another secret": make_token("not-the-secret" * 3, addon.id),
                   "a token made for another add-on": make_token(SECRET, f"not-{addon.id}"),
                   "an expired token": make_token(SECRET, addon.id, issued=time.time() - 3600)}
        for path in self.protected:
            for what, token in refused.items():
                status = addon.get(path, token)
                assert status in (401, 403), (
                    f"GET {path} with {what} answered {status}: anyone on this machine could act as "
                    f"anyone. Read who is asking from X-Elysium-Identity, verified "
                    f"(elysium_addon.identity), and answer 401 when it does not verify.")
            assert addon.get(path, good) not in (401, 403, 0), (
                f"GET {path} refused a good token: this check would pass a server that refuses "
                f"everybody, so it needs one path that lets a signed-in person in.")

    def test_it_listens_on_loopback_only(self, addon):
        assert addon.until_healthy(self.start_seconds), addon.said()
        elsewhere = _this_machine_elsewhere()
        if elsewhere is None:
            pytest.skip("this machine has no address but loopback to try")
        assert addon.get(addon.health, host=elsewhere) == 0, (
            f"it answers on {elsewhere}, not only 127.0.0.1: listen on 127.0.0.1, so Elysium's "
            f"proxy is the only way in.")

    def test_sigterm_ends_it_within_its_deadline_cleanly(self, addon):
        assert addon.until_healthy(self.start_seconds), addon.said()
        os.killpg(addon.process.pid, signal.SIGTERM)
        status = addon.ended_within(addon.stop_seconds)
        assert status is not None, (
            f"still running {addon.stop_seconds:g} s after SIGTERM, the manifest's stopSeconds: "
            f"Elysium would SIGKILL it, mid-whatever it was doing.")
        assert status == 0, (
            f"it ended with status {status} after SIGTERM, not 0: tidy up on SIGTERM and leave "
            f"normally. Its output:\n{addon.said()}")

    def test_it_leaves_when_elysium_does(self, addon):
        assert addon.until_healthy(self.start_seconds), addon.said()
        addon.process.stdin.close()
        assert addon.ended_within(addon.stop_seconds) is not None, (
            f"still running {addon.stop_seconds:g} s after its standard input closed: when Elysium "
            f"is killed nothing sends SIGTERM, and this server would run on with nobody to stop it. "
            f"Call elysium_addon.exit_when_elysium_does().")
