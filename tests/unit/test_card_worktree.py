"""tools/card_worktree.sh and tools/integrate_card.sh, in a throwaway repository."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"

ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def run(*cmd, cwd):
    return subprocess.run(
        [str(c) for c in cmd], cwd=cwd, env=ENV, text=True, capture_output=True
    )


def git(cwd, *args):
    result = run("git", *args, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def commit_file(cwd, name, text, message):
    path = Path(cwd) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(cwd, "add", "--", name)
    git(cwd, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    """tmp/main is the main worktree on dev; worktrees go in tmp/elysium-wt."""
    main = tmp_path / "elysium-main"
    main.mkdir()
    git(main, "init", "-q", "-b", "dev")
    (main / "tools").mkdir()
    for script in ("card_worktree.sh", "integrate_card.sh"):
        shutil.copy(TOOLS / script, main / "tools" / script)
    (main / "check.sh").write_text("#!/bin/sh\nexit 0\n")
    (main / "check.sh").chmod(0o755)
    (main / "shared.txt").write_text("base\n")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "base")
    return main


def worktree_of(main, card):
    return main.parent / "elysium-wt" / card


def start(main, card):
    return run("bash", main / "tools" / "card_worktree.sh", card, cwd=main)


def integrate(main, card):
    return run("bash", main / "tools" / "integrate_card.sh", card, cwd=main)


def test_card_worktree_creates_worktree_and_branch(repo):
    result = start(repo, "X-01")
    assert result.returncode == 0, result.stderr
    wt = worktree_of(repo, "X-01")
    assert (wt / "shared.txt").exists()
    assert git(wt, "rev-parse", "--abbrev-ref", "HEAD") == "card/X-01"
    assert git(repo, "rev-parse", "card/X-01") == git(repo, "rev-parse", "dev")


def test_card_worktree_writes_the_packet_when_the_tool_exists(repo):
    (repo / "tools" / "card_packet.py").write_text(
        "import sys\nprint('packet for', sys.argv[1])\n"
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "packet tool")
    result = start(repo, "X-02")
    assert result.returncode == 0, result.stderr
    packet = worktree_of(repo, "X-02") / ".heavy" / "packet.md"
    assert result.stdout.strip() == str(packet.resolve())
    assert packet.read_text() == "packet for X-02\n"


def test_card_worktree_refuses_a_second_call(repo):
    assert start(repo, "X-01").returncode == 0
    again = start(repo, "X-01")
    assert again.returncode != 0
    assert "already exists" in again.stderr


def test_card_worktree_refuses_an_existing_directory(repo):
    worktree_of(repo, "X-03").mkdir(parents=True)
    result = start(repo, "X-03")
    assert result.returncode != 0
    assert run("git", "rev-parse", "--verify", "card/X-03", cwd=repo).returncode != 0


def test_a_clean_card_ends_fast_forwarded(repo):
    assert start(repo, "X-01").returncode == 0
    wt = worktree_of(repo, "X-01")
    commit_file(wt, "card.txt", "card\n", "card work")
    commit_file(repo, "other.txt", "dev moved\n", "dev moves on")
    result = integrate(repo, "X-01")
    assert result.returncode == 0, result.stderr
    assert git(repo, "rev-parse", "dev") == git(repo, "rev-parse", "card/X-01")
    assert (repo / "card.txt").exists() and (repo / "other.txt").exists()
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "dev"
    assert git(repo, "rev-list", "--merges", "--count", "dev") == "0"


def test_the_exit_status_is_the_check_status(repo):
    assert start(repo, "X-01").returncode == 0
    commit_file(worktree_of(repo, "X-01"), "card.txt", "card\n", "card work")
    (repo / "check.sh").write_text("#!/bin/sh\nexit 7\n")
    git(repo, "commit", "-q", "-am", "failing check")
    assert integrate(repo, "X-01").returncode == 7


def test_a_conflict_in_a_normal_file_exits_6_and_leaves_dev(repo):
    assert start(repo, "X-01").returncode == 0
    wt = worktree_of(repo, "X-01")
    commit_file(wt, "shared.txt", "card side\n", "card edits shared")
    commit_file(repo, "shared.txt", "dev side\n", "dev edits shared")
    dev_before = git(repo, "rev-parse", "dev")
    card_before = git(repo, "rev-parse", "card/X-01")
    result = integrate(repo, "X-01")
    assert result.returncode == 6
    assert "shared.txt" in result.stderr
    assert git(repo, "rev-parse", "dev") == dev_before
    assert git(repo, "rev-parse", "card/X-01") == card_before
    assert git(wt, "status", "--porcelain") == ""
    assert (repo / "shared.txt").read_text() == "dev side\n"


def test_a_conflict_in_a_generated_file_without_its_tool_exits_6(repo):
    commit_file(repo, "quality/ruff-ignores.txt", "base\n", "baseline")
    assert start(repo, "X-01").returncode == 0
    commit_file(
        worktree_of(repo, "X-01"), "quality/ruff-ignores.txt", "card\n", "card"
    )
    commit_file(repo, "quality/ruff-ignores.txt", "dev\n", "dev")
    dev_before = git(repo, "rev-parse", "dev")
    result = integrate(repo, "X-01")
    assert result.returncode == 6
    assert git(repo, "rev-parse", "dev") == dev_before


def test_a_conflict_in_a_generated_file_is_regenerated(repo):
    commit_file(repo, "quality/ruff-ignores.txt", "base\n", "baseline")
    commit_file(
        repo,
        "tools/ruff_baseline.py",
        "from pathlib import Path\n"
        "Path('quality/ruff-ignores.txt').write_text('regenerated\\n')\n",
        "the baseline tool",
    )
    assert start(repo, "X-01").returncode == 0
    wt = worktree_of(repo, "X-01")
    commit_file(wt, "quality/ruff-ignores.txt", "card\n", "card baseline")
    commit_file(wt, "card.txt", "card\n", "card work")
    commit_file(repo, "quality/ruff-ignores.txt", "dev\n", "dev baseline")
    result = integrate(repo, "X-01")
    assert result.returncode == 0, result.stderr
    assert (repo / "quality" / "ruff-ignores.txt").read_text() == "regenerated\n"
    assert (repo / "card.txt").exists()
    assert git(repo, "rev-parse", "dev") == git(repo, "rev-parse", "card/X-01")
