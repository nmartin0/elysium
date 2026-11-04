"""with_server.sh runs a command against a server of its own (marker: live)."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "with_server.sh"

pytestmark = pytest.mark.live


def run(*args):
    return subprocess.run(  # noqa: S603 -- fixed script
        [str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT, timeout=180, check=False)


def test_the_command_sees_a_ready_server_and_its_status_is_returned():
    result = run("--", "bash", "-c", 'curl -fsS "$ELYSIUM_URL/api/health" >/dev/null && exit 7')

    assert result.returncode == 7, result.stderr


def test_the_server_is_gone_afterwards():
    result = run("--", "bash", "-c", 'echo "$ELYSIUM_URL"')
    url = result.stdout.strip()

    assert result.returncode == 0 and url.startswith("http://127.0.0.1:")
    gone = subprocess.run(["curl", "-fsS", "--max-time", "2", url + "/api/health"],  # noqa: S603, S607 -- fixed
                          capture_output=True, check=False)
    assert gone.returncode != 0


def test_no_command_is_a_usage_error():
    assert run().returncode == 2
    assert run("--port", "9").returncode == 2
