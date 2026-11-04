"""The git hooks and the agent hook refuse what they are for."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
PLANTED = hashlib.sha256(b"planted").hexdigest()


@pytest.fixture
def repo(tmp_path):
    """A repository with the project's tools and hooks, hooks switched on."""
    for name in (".githooks", "tools", "quality", ".claude"):
        shutil.copytree(ROOT / name, tmp_path / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "src").mkdir()

    def git(*args, check=True, env=None):
        return subprocess.run(  # noqa: S603, S607 -- fixed command
            ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com",  # noqa: S607 -- fixed command
             "-c", "core.hooksPath=.githooks", *args],
            capture_output=True, text=True, check=check, env={**os.environ, **(env or {})})

    git("init", "-q", "-b", "card/T0.1")
    (tmp_path / ".gitignore").write_text("__pycache__/\n")
    git("-c", "core.hooksPath=/dev/null", "add", ".")
    git("-c", "core.hooksPath=/dev/null", "commit", "-q", "-m", "base")
    git.root = tmp_path
    return git


PLANT = {"ELYSIUM_NAME_GUARD_EXTRA": PLANTED}


def test_pre_commit_refuses_vendor_name(repo):
    (repo.root / "notes.md").write_text("a planted word\n")
    repo("add", "notes.md")

    result = repo("commit", "-q", "-m", "Notes\n\nCard: T0.1", check=False, env=PLANT)

    assert result.returncode != 0
    assert "notes.md:1" in result.stdout + result.stderr


def test_pre_commit_passes_a_clean_file(repo):
    (repo.root / "notes.md").write_text("a plain sentence\n")
    repo("add", "notes.md")

    result = repo("commit", "-q", "-m", "Notes\n\nCard: T0.1", check=False, env=PLANT)

    assert result.returncode == 0, result.stderr


def test_pre_commit_refuses_history_in_a_source_comment(repo):
    (repo.root / "src" / "a.py").write_text("x = 1  # see GOLD-9\n")
    repo("add", "src/a.py")

    result = repo("commit", "-q", "-m", "A\n\nCard: T0.1\nControls-Added: none\nControls-Deleted: none\n"
                  "Invariants: none", check=False)

    assert result.returncode != 0
    assert "ticket code" in result.stdout + result.stderr


def test_pre_commit_runs_ruff_on_staged_files(repo):
    (repo.root / "tools" / "unused.py").write_text("import os\n")
    repo("add", "tools/unused.py")

    result = repo("commit", "-q", "-m", "A\n\nCard: T0.1", check=False)

    assert result.returncode != 0
    assert "F401" in result.stdout + result.stderr


def test_commit_msg_refuses_an_attribution_trailer(repo):
    (repo.root / "notes.md").write_text("fine\n")
    repo("add", "notes.md")

    result = repo("commit", "-q", "-m", "Notes\n\nCard: T0.1\nCo-Authored-By: A Person <a@example.com>", check=False)

    assert result.returncode != 0
    assert "no attribution trailers" in result.stderr


def test_commit_msg_refuses_a_missing_card_trailer(repo):
    (repo.root / "notes.md").write_text("fine\n")
    repo("add", "notes.md")

    result = repo("commit", "-q", "-m", "Notes\n\nA body.", check=False)

    assert result.returncode != 0
    assert "Card: is missing" in result.stderr


def test_commit_msg_refuses_a_planted_name_in_the_message(repo):
    (repo.root / "notes.md").write_text("fine\n")
    repo("add", "notes.md")

    result = repo("commit", "-q", "-m", "A planted message\n\nCard: T0.1", check=False, env=PLANT)

    assert result.returncode != 0
    assert "the precedent" in result.stderr


def test_commit_msg_refuses_an_oversized_commit_without_large_change(repo):
    (repo.root / "big.txt").write_text("x\n" * 1200)
    repo("add", "big.txt")

    refused = repo("commit", "-q", "-m", "Big\n\nCard: T0.1", check=False)
    allowed = repo("commit", "-q", "-m", "Big\n\nCard: T0.1\nLarge-change: a data file", check=False)

    assert refused.returncode != 0
    assert "Large-change" in refused.stderr
    assert allowed.returncode == 0, allowed.stderr


def test_commit_msg_asks_for_the_lists_when_src_changes(repo):
    (repo.root / "src" / "a.py").write_text("x = 1\n")
    repo("add", "src/a.py")

    result = repo("commit", "-q", "-m", "A\n\nCard: T0.1", check=False)

    assert result.returncode != 0
    assert "Controls-Added: is missing" in result.stderr


def pretool(repo, command):
    return subprocess.run(  # noqa: S603, S607 -- fixed command
        ["python3", str(repo.root / "tools" / "commit_msg_check.py"), "--claude-pretool"],  # noqa: S607 -- fixed command
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True, text=True, check=False, cwd=repo.root, env={**os.environ, **PLANT})


def test_the_agent_hook_refuses_a_commit_of_a_bad_file(repo):
    (repo.root / "notes.md").write_text("a planted word\n")
    repo("add", "notes.md")

    result = pretool(repo, "git commit -m 'Notes'")

    assert result.returncode == 2
    assert "notes.md" in result.stderr


def test_the_agent_hook_refuses_an_attribution_trailer_in_the_message(repo):
    (repo.root / "notes.md").write_text("fine\n")
    repo("add", "notes.md")

    result = pretool(repo, "git commit -m 'Notes' -m 'Card: T0.1\nCo-Authored-By: A <a@example.com>'")

    assert result.returncode == 2


def test_the_agent_hook_lets_other_commands_through(repo):
    (repo.root / "notes.md").write_text("a planted word\n")
    repo("add", "notes.md")

    assert pretool(repo, "git status").returncode == 0
    assert pretool(repo, "echo git commit is a phrase").returncode == 0


def test_the_agent_hook_passes_a_clean_commit(repo):
    (repo.root / "notes.md").write_text("fine\n")
    repo("add", "notes.md")

    assert pretool(repo, "git commit -m 'Notes' -m 'Card: T0.1'").returncode == 0


def test_the_settings_declare_the_agent_hook():
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text())
    (entry,) = settings["hooks"]["PreToolUse"]

    assert entry["matcher"] == "Bash"
    assert "commit_msg_check.py --claude-pretool" in entry["hooks"][0]["command"]


def test_setup_dev_prints_the_hooks_path_command():
    result = subprocess.run(  # noqa: S603, S607 -- fixed command
        ["bash", str(ROOT / "tools" / "setup_dev.sh")], capture_output=True, text=True, check=True)  # noqa: S607 -- fixed command

    assert "git config core.hooksPath .githooks" in result.stdout
