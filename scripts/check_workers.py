"""Start this deployment under `uvicorn --workers 2` and check that what
must be shared between worker processes is.

    python -m scripts.check_workers

Uses the deployment the usual environment variables name, and the two
accounts scripts/create_e2e_users.py makes (create them first). Starts
its own server on a free port and stops it afterwards, so a server you
already have running is not touched.

WHY A SCRIPT. BLOCKING.md carried "--workers for real" for months
because the only evidence was two apps inside one test process. Running
it found two faults those tests could not see (14 Oct): the generation
header alternated between workers, so the UI refetched its schema on
almost every request, and a starting worker's crash recovery could take
a write another worker was still applying. Both are fixed and unit
tested; this is how to see the whole thing work on a real machine.

HOW IT KNOWS BOTH WORKERS ANSWERED, rather than assuming: every request
opens a fresh connection, so the kernel hands it to whichever worker
accepts next, and the server's access log carries each worker's pid.
A check that only ever reached one worker FAILS rather than passing.

WHAT IT CHECKS
  - a session made on one worker is honoured by every worker
  - every worker sends the same x-elysium-configuration header
  - failed logins spread over the workers still lock an account
It changes nothing in the deployment except recording failed logins
for a username that does not exist.
"""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

LOG_CONFIG = {
    "version": 1, "disable_existing_loggers": False,
    "formatters": {"pid": {"format": "%(process)d %(name)s %(message)s"}},
    "handlers": {"out": {"class": "logging.StreamHandler", "formatter": "pid",
                         "stream": "ext://sys.stdout"}},
    "loggers": {"uvicorn": {"handlers": ["out"], "level": "INFO"},
                "uvicorn.access": {"handlers": ["out"], "level": "INFO", "propagate": False}},
}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _workers_that_answered(log: Path, mark: int, fragment: str) -> set[str]:
    lines = log.read_text().splitlines()[mark:]
    return {line.split()[0] for line in lines if "uvicorn.access" in line and fragment in line}


def main() -> int:
    import requests

    scratch = Path(tempfile.mkdtemp(prefix="elysium-workers-"))
    (scratch / "log.json").write_text(json.dumps(LOG_CONFIG))
    log = scratch / "server.log"
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    with open(log, "w") as out:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api.app:app", "--port", str(port),
             "--workers", "2", "--log-config", str(scratch / "log.json")],
            stdout=out, stderr=subprocess.STDOUT, env=os.environ.copy())
    failures = 0

    def check(name: str, ok: bool, detail: str) -> None:
        nonlocal failures
        failures += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name} -- {detail}")

    try:
        for _ in range(120):
            if log.read_text().count("Application startup complete") >= 2:
                break
            if server.poll() is not None:
                print(log.read_text()[-2000:])
                print("The server exited while starting; its log is above.")
                return 1
            time.sleep(0.5)
        else:
            print("Two workers did not finish starting within a minute.")
            return 1

        session = requests.Session()
        login = session.post(f"{base}/api/login",
                             json={"username": "plainuser", "password": "plainpass123"})
        if login.status_code not in (200, 204):
            print("Could not log in as plainuser. Run, from the repository root:\n"
                  "    python -m scripts.create_e2e_users --yes-this-is-development")
            return 1
        cookies = dict(session.cookies)

        mark = len(log.read_text().splitlines())
        answers = [requests.get(f"{base}/api/me", cookies=cookies,
                                headers={"Connection": "close"}) for _ in range(40)]
        time.sleep(0.5)
        workers = _workers_that_answered(log, mark, "/api/me")
        check("one session, every worker",
              {a.status_code for a in answers} == {200} and len(workers) >= 2,
              f"40 requests, {len(workers)} worker(s) answered, statuses "
              f"{sorted({a.status_code for a in answers})}")
        configurations = {a.headers.get("x-elysium-configuration") for a in answers}
        generations = {a.headers.get("x-elysium-generation") for a in answers}
        check("every worker names the same configuration",
              len(configurations) == 1 and None not in configurations,
              f"configuration {sorted(map(str, configurations))}, "
              f"generations {sorted(map(str, generations))}")

        nobody = f"nobody-{uuid.uuid4().hex[:8]}"
        mark = len(log.read_text().splitlines())
        for _ in range(6):
            requests.post(f"{base}/api/login", json={"username": nobody, "password": "x"},
                          headers={"Connection": "close"})
        time.sleep(0.5)
        workers = _workers_that_answered(log, mark, "/api/login")
        # ASKED OF THE SHARED STORE, because the HTTP answer cannot tell:
        # a lockout is deliberately identical to a wrong password.
        from core.auth.login_attempt_tracker import LoginAttemptTracker
        from core.deployment_loader import resolve_runtime_paths

        tracker = LoginAttemptTracker(resolve_runtime_paths().data_dir / "credentials.db")
        locked = tracker.is_locked_out(nobody)
        check("failed logins counted across workers",
              locked and len(workers) >= 2,
              f"6 failures over {len(workers)} worker(s); locked out: {locked}")
    finally:
        server.terminate()
        try:
            server.wait(20)
        except subprocess.TimeoutExpired:
            server.kill()

    print("\nAll checks passed." if not failures else f"\n{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
