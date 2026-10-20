"""A real PostgreSQL for the tests that need one, or a loud failure.

WHY THIS EXISTS. The SQLAlchemy adapter is the production read path,
and its only real-engine tests started a server through `pgserver`,
which ships PostgreSQL as a wheel -- for Python 3.12 and earlier. The
machine that gates every patch moved to 3.13, `pytest.importorskip`
turned the missing wheel into a SKIP, and the suite went on reporting
green with the production read path untested. BLOCKING.md (then item 3)
predicted exactly that ("a 3.13 environment would skip these
silently"); it then happened, unnoticed, until it was looked for.

THREE WAYS TO GET ONE, tried in order:

  1. `pgserver`, where its wheel exists.
  2. PostgreSQL's own binaries -- `initdb` and `pg_ctl` on PATH, or
     under /usr/lib/postgresql/<version>/bin as Debian and Ubuntu
     install them. A throwaway cluster in a temporary directory,
     listening on a unix socket only, never on a network port.
  3. NEITHER IS A FAILURE, not a skip -- the owner's call (2026-10-12):
     a suite that cannot test the production read path must say so in
     red. Install PostgreSQL (`apt install postgresql`, `brew install
     postgresql`) or run on Python 3.12 with requirements-dev.txt.

AS ROOT, `initdb` refuses to run, so the cluster is created and started
as the `postgres` user through `runuser` -- which is how this container
has to do it; a developer's own machine never reaches that branch.
"""

import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

NONE_AVAILABLE = (
    "No PostgreSQL to test the production read path against: `pgserver` is not "
    "installed (it has no wheel for this Python) and no `initdb`/`pg_ctl` was found "
    "on PATH or under /usr/lib/postgresql. Install PostgreSQL, or run the suite on "
    "Python 3.12 with requirements-dev.txt. This FAILS rather than skips on purpose: "
    "a skipped test here is the production read path silently untested."
)


def _binaries() -> "Path | None":
    """The directory holding initdb and pg_ctl, newest version first."""
    on_path = shutil.which("pg_ctl")
    if on_path and shutil.which("initdb"):
        return Path(on_path).parent
    candidates = sorted(glob.glob("/usr/lib/postgresql/*/bin"),
                        key=lambda p: int(Path(p).parent.name) if Path(p).parent.name.isdigit() else 0,
                        reverse=True)
    for candidate in candidates:
        if (Path(candidate) / "initdb").exists() and (Path(candidate) / "pg_ctl").exists():
            return Path(candidate)
    return None


class _SystemCluster:
    def __init__(self, bin_dir: Path):
        self.bin_dir = bin_dir
        self.root = Path(tempfile.mkdtemp(prefix="elysium-pg-"))
        self.data = self.root / "data"
        self.socket_dir = self.root / "sock"
        self.socket_dir.mkdir()
        self._as_root = os.geteuid() == 0
        if self._as_root:
            shutil.chown(self.root, "postgres")
            shutil.chown(self.socket_dir, "postgres")
        self.user = "postgres" if self._as_root else os.environ.get("USER") or "postgres"

    def _run(self, *argv: str) -> None:
        command = [str(self.bin_dir / argv[0]), *argv[1:]]
        if self._as_root:
            command = ["runuser", "-u", "postgres", "--", *command]
        subprocess.run(command, check=True, capture_output=True, text=True)

    def start(self) -> str:
        self._run("initdb", "-D", str(self.data), "-A", "trust", "-U", self.user, "--no-sync")
        # A UNIX SOCKET ONLY: listen_addresses='' means no TCP port is
        # opened, so a test cluster is never reachable from the network
        # and two concurrent suites cannot collide on a port.
        self._run("pg_ctl", "-D", str(self.data), "-w", "-l", str(self.root / "log"),
                  "-o", f"-c listen_addresses='' -k {self.socket_dir} -F", "start")
        return f"postgresql://{self.user}@/postgres?host={self.socket_dir}"

    def stop(self) -> None:
        try:
            self._run("pg_ctl", "-D", str(self.data), "-m", "immediate", "stop")
        except subprocess.CalledProcessError:
            pass
        shutil.rmtree(self.root, ignore_errors=True)


def real_postgres():
    """(uri, stop) for a real PostgreSQL, or pytest.fail with the reason.

    The uri is plain `postgresql://`; SQLAlchemy callers replace the
    scheme with `postgresql+psycopg://` as they always have.
    """
    try:
        import pgserver
    except ImportError:
        pgserver = None
    if pgserver is not None:
        server = pgserver.get_server(tempfile.mkdtemp())
        return server.get_uri(), lambda: None

    bin_dir = _binaries()
    if bin_dir is None:
        pytest.fail(NONE_AVAILABLE, pytrace=False)
    cluster = _SystemCluster(bin_dir)
    try:
        return cluster.start(), cluster.stop
    except subprocess.CalledProcessError as exc:
        cluster.stop()
        pytest.fail(f"PostgreSQL at {bin_dir} would not start: {exc.stderr.strip()[-500:]}",
                    pytrace=False)


class _StandbyCluster(_SystemCluster):
    """A hot standby of a running cluster, by pg_basebackup -R over the
    primary's socket (21 October): for the tests of a source that lags.
    Its own socket directory, so both listen on the same port number."""

    def start_from(self, primary: _SystemCluster) -> str:
        self._run("pg_basebackup", "-D", str(self.data), "-h", str(primary.socket_dir),
                  "-U", primary.user, "-R", "-X", "stream", "-c", "fast")
        self._run("pg_ctl", "-D", str(self.data), "-w", "-l", str(self.root / "log"),
                  "-o", f"-c listen_addresses='' -k {self.socket_dir} -F", "start")
        return f"postgresql://{self.user}@/postgres?host={self.socket_dir}"


def real_postgres_standby():
    """(primary uri, standby uri, stop): a PostgreSQL and a streaming
    standby of it, from the system's binaries (pgserver cannot make one),
    or pytest.fail with the reason."""
    bin_dir = _binaries()
    if bin_dir is None or not (bin_dir / "pg_basebackup").exists():
        pytest.fail(f"{NONE_AVAILABLE} A standby also needs pg_basebackup.", pytrace=False)
    primary, standby = _SystemCluster(bin_dir), _StandbyCluster(bin_dir)

    def stop():
        standby.stop()
        primary.stop()

    try:
        return primary.start(), standby.start_from(primary), stop
    except subprocess.CalledProcessError as exc:
        stop()
        pytest.fail(f"a PostgreSQL standby would not start: {exc.stderr.strip()[-500:]}",
                    pytrace=False)
