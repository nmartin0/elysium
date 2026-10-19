"""A real MariaDB for the tests that need one, or a loud failure.

WHY THIS EXISTS. MariaDB reaches Elysium through the SQLAlchemy adapter,
which already read it correctly against the simulator's world (19
October) -- and had no test that would notice if it stopped. Its
behaviour differs from PostgreSQL's exactly where the adapter has
per-dialect code: the query time limit, connection lifetime, and the
read-only session. Those are only checkable against the real engine.

THE SAME SHAPE AS tests/postgres_server.py, deliberately: a throwaway
server in a temporary directory, on a UNIX SOCKET ONLY (`skip-networking`,
so no port is opened and two suites cannot collide), stopped and deleted
afterwards.

NONE AVAILABLE IS A FAILURE, not a skip -- the owner's rule for
PostgreSQL (2026-10-12) applied to the second server engine: a suite that
cannot test a read path must say so in red. Install MariaDB
(`apt install mariadb-server`, `brew install mariadb`).

AS ROOT, mariadbd refuses to run unless told a user, so it runs as
`mysql`, which the Debian and Ubuntu package creates, and owns its
directory. A developer's own machine never reaches that branch.

ROOT HAS NO PASSWORD (`--auth-root-authentication-method=normal`), so a
test running as any OS user can connect -- reachable only through a
socket in a directory this process created.
"""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

NONE_AVAILABLE = (
    "No MariaDB to test its read path against: no `mariadbd` and "
    "`mariadb-install-db` were found on PATH or in /usr/sbin. Install MariaDB "
    "(`apt install mariadb-server`, `brew install mariadb`). This FAILS rather than "
    "skips on purpose: a skipped test here is a read path silently untested."
)


def _binary(name: str) -> "str | None":
    return shutil.which(name) or (f"/usr/sbin/{name}" if Path(f"/usr/sbin/{name}").exists() else None)


class _Server:
    def __init__(self, server: str, install: str):
        self.server, self.install = server, install
        self.root = Path(tempfile.mkdtemp(prefix="elysium-mariadb-"))
        self.data = self.root / "data"
        self.socket = self.root / "mariadb.sock"
        self._as_root = os.geteuid() == 0
        self._process: subprocess.Popen | None = None
        if self._as_root:
            shutil.chown(self.root, "mysql")

    def _user_args(self) -> list[str]:
        return ["--user=mysql"] if self._as_root else []

    def start(self) -> str:
        subprocess.run([self.install, "--no-defaults", f"--datadir={self.data}",
                        "--auth-root-authentication-method=normal", "--skip-test-db",
                        *self._user_args()],
                       check=True, capture_output=True, text=True)
        self._process = subprocess.Popen(
            [self.server, "--no-defaults", f"--datadir={self.data}", f"--socket={self.socket}",
             "--skip-networking", f"--pid-file={self.root / 'pid'}",
             f"--log-error={self.root / 'log'}", *self._user_args()],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 60
        while not self.socket.exists():
            if self._process.poll() is not None or time.monotonic() > deadline:
                log = (self.root / "log").read_text(errors="replace") if (self.root / "log").exists() else ""
                raise subprocess.CalledProcessError(1, self.server, stderr=log)
            time.sleep(0.1)
        import pymysql

        with pymysql.connect(unix_socket=str(self.socket), user="root") as conn, conn.cursor() as cur:
            cur.execute("CREATE DATABASE elysium_test CHARACTER SET utf8mb4")
        return f"mariadb+pymysql://root@localhost/elysium_test?unix_socket={self.socket}&charset=utf8mb4"

    def stop(self) -> None:
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self._process.kill()
        shutil.rmtree(self.root, ignore_errors=True)


def real_mariadb():
    """(sqlalchemy_url, stop) for a real MariaDB, or pytest.fail with the
    reason. The database is `elysium_test`, empty, utf8mb4."""
    server, install = _binary("mariadbd"), _binary("mariadb-install-db")
    if server is None or install is None:
        pytest.fail(NONE_AVAILABLE, pytrace=False)
    instance = _Server(server, install)
    try:
        return instance.start(), instance.stop
    except subprocess.CalledProcessError as exc:
        instance.stop()
        pytest.fail(f"MariaDB at {server} would not start: {(exc.stderr or '').strip()[-500:]}",
                    pytrace=False)
