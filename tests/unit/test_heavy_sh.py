"""tools/heavy.sh logs a command and records its exit status."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def run_heavy(repo: Path, *args: str, timeout: str | None = None):
    env = {**os.environ}
    if timeout:
        env["HEAVY_TIMEOUT"] = timeout
    return subprocess.run(  # noqa: S603 -- fixed command
        ["bash", str(ROOT / "tools" / "heavy.sh"), *args],  # noqa: S607 -- fixed command
        cwd=repo,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def make_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607 -- fixed command
    return tmp_path


def test_exit_code_is_recorded(tmp_path):
    repo = make_repo(tmp_path)

    result = run_heavy(repo, "demo", "bash", "-c", "echo hello; exit 7")

    assert result.returncode == 7
    (exit_file,) = (repo / ".heavy").glob("*-demo.exit")
    (log_file,) = (repo / ".heavy").glob("*-demo.log")
    assert exit_file.read_text().strip() == "7"
    assert "hello" in log_file.read_text()
    assert "hello" in result.stdout


def test_a_pipe_failure_inside_the_command_is_not_hidden(tmp_path):
    repo = make_repo(tmp_path)

    result = run_heavy(repo, "piped", "bash", "-c", "set -o pipefail; (exit 3) | cat")

    assert result.returncode == 3


def test_the_timeout_stops_the_command(tmp_path):
    repo = make_repo(tmp_path)

    result = run_heavy(repo, "slow", "sleep", "30", timeout="1")

    assert result.returncode == 124
    (exit_file,) = (repo / ".heavy").glob("*-slow.exit")
    assert exit_file.read_text().strip() == "124"


def test_only_the_last_sixty_lines_are_printed(tmp_path):
    repo = make_repo(tmp_path)

    result = run_heavy(repo, "long", "bash", "-c", "seq 1 200")

    assert "\n200\n" in result.stdout
    assert "\n140\n" not in result.stdout
    assert result.stdout.startswith("141\n")


def test_a_full_run_takes_the_shared_lock(tmp_path):
    repo = make_repo(tmp_path)
    lock = repo / ".git" / "heavy-full.lock"

    result = run_heavy(repo, "full", "true")

    assert result.returncode == 0
    assert lock.exists()


def test_a_bad_name_is_refused(tmp_path):
    repo = make_repo(tmp_path)

    assert run_heavy(repo, "../x", "true").returncode == 2
    assert run_heavy(repo, "only-a-name").returncode == 2
