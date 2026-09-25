"""Every script that creates a known-password account refuses without
the flag (001's F-30).

WHAT WENT WRONG. create_debug_user.py refused without
--yes-this-is-development. create_colleague_user.py creates the SAME
account -- 'debug' / 'a', every grant the deployment defines -- and
refused nothing. So the guard was walkable-around by running the other
script, and nothing failed when it was.

WHY THIS FILE DISCOVERS SCRIPTS RATHER THAN LISTING THEM. A list is a
thing somebody forgets to add to, which is how F-30 happened in the
first place: two scripts were guarded because two people remembered.
Globbing scripts/create_*_user.py means a FOURTH script is covered the
day it is written, and fails this file until it is guarded.

WHY IT CALLS main() RATHER THAN READING THE SOURCE.
tests/unit/test_template_is_a_valid_deployment.py asserts the literal
strings "--yes-this-is-development" and "REFUSING" appear in
create_debug_user.py's source. AGENTS.md records why that shape is not
a test: it is satisfied by deleting the behaviour and leaving the word
in a comment. These call the script and look at what it did.

bootstrap_root.py is deliberately NOT in scope: it generates its
password with secrets.token_urlsafe(24) and prints it once, so there is
no known password to guard. The glob encodes that distinction -- it
matches create_*_user.py, not every script that calls create_user().
"""

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "integration" / "fixtures"

GUARDED_SCRIPTS = sorted(p.stem for p in (REPO_ROOT / "scripts").glob("create_*_user*.py"))


def _accounts(data_dir: Path) -> list[str]:
    """Every username on disk, or [] if nothing was ever created."""
    db = data_dir / "credentials.db"
    if not db.exists():
        return []
    with sqlite3.connect(db) as conn:
        return [row[0] for row in conn.execute("SELECT username FROM users")]


def _run(script: str, argv: list[str], tmp_path: Path, monkeypatch) -> int:
    monkeypatch.setenv("ELYSIUM_CONFIG_DIR", str(FIXTURES))
    monkeypatch.setenv("ELYSIUM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ELYSIUM_LOG_DIR", str(tmp_path / "log"))
    monkeypatch.setattr(sys, "argv", [f"scripts/{script}.py", *argv])
    module = importlib.import_module(f"scripts.{script}")
    return module.main()


def test_there_is_at_least_one_script_to_guard():
    """A glob that matched nothing would make every test below vacuous."""
    assert GUARDED_SCRIPTS, "scripts/create_*_user*.py matched nothing"


@pytest.mark.parametrize("script", GUARDED_SCRIPTS)
def test_it_refuses_without_the_flag_and_creates_nothing(script, tmp_path, monkeypatch, capsys):
    # THE ROW COUNT, not only the exit code. A script that returned 1
    # after creating the account would satisfy a status-only assertion
    # and still have left the back door open.
    assert _run(script, [], tmp_path, monkeypatch) == 1
    assert _accounts(tmp_path) == []
    assert "REFUSING" in capsys.readouterr().err


@pytest.mark.parametrize("script", GUARDED_SCRIPTS)
def test_the_refusal_names_the_command_that_would_work(script, tmp_path, monkeypatch, capsys):
    """A refusal that does not say how to proceed gets worked around."""
    _run(script, [], tmp_path, monkeypatch)

    message = capsys.readouterr().err
    assert f"python -m scripts.{script}" in message
    assert "--yes-this-is-development" in message


@pytest.mark.parametrize("script", GUARDED_SCRIPTS)
def test_but_with_the_flag_it_does_its_job(script, tmp_path, monkeypatch):
    """THE OPPOSITE DIRECTION. A guard that always refused would pass
    every test above while making the scripts useless -- so assert the
    legitimate path still works, or the guard is only proved to be
    obstructive."""
    assert _run(script, ["--yes-this-is-development"], tmp_path, monkeypatch) == 0
    assert _accounts(tmp_path), f"{script} created nothing even with the flag"


def test_the_colleague_script_cannot_be_used_to_dodge_the_debug_guard():
    """F-30 EXACTLY, as a single named case, because the general rule
    above would still pass if this one script stopped creating 'debug'
    for some unrelated reason -- and then the regression that matters
    would be untested."""
    source = (REPO_ROOT / "scripts" / "create_colleague_user.py").read_text()

    # It genuinely still creates 'debug': that is what made the bypass
    # total, and it is why guarding THIS script was the fix rather than
    # removing the account from it.
    assert "debug" in source


@pytest.mark.parametrize("script", GUARDED_SCRIPTS)
def test_refusing_happens_before_the_deployment_is_touched(script, tmp_path, monkeypatch):
    """A script certain to refuse should not first load a deployment or
    create a data directory. Checked because create_debug_user.py does
    its role check first, so an unguarded run still did work."""
    _run(script, [], tmp_path, monkeypatch)

    created = [p.name for p in tmp_path.iterdir()] if tmp_path.exists() else []
    assert created == [], f"{script} created {created} before refusing"
