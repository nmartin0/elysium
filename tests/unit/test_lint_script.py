"""
lint.sh can fail -- every step, not only most of them.

004-F1: the lock-file step set FAILED=1, a variable nothing read. Drift
printed its warning directly above "All checks passed." and lint.sh
exited 0. The checker was right; its wiring was not, and nothing tested
the wiring. Its commit was titled "... fail the lint if they drift".
"""

import re
from pathlib import Path

import pytest

import scripts.check_lockfiles as check_lockfiles

ROOT = Path(__file__).resolve().parent.parent.parent


class TestEveryStepCanFailTheScript:
    def test_every_failure_sets_the_variable_the_script_exits_with(self):
        """A SOURCE-LEVEL TRIPWIRE for the whole class: any `|| NAME=1`
        naming a variable other than the one `exit` returns is a step
        whose failure is thrown away."""
        script = (ROOT / "lint.sh").read_text()
        (exit_var,) = re.findall(r'^exit "\$(\w+)"', script, re.M)
        on_failure = re.findall(r"\|\|\s*(\w+)=1", script)

        assert on_failure, "no failing steps found -- the pattern has drifted"
        assert set(on_failure) == {exit_var}, (
            f"a step sets {set(on_failure) - {exit_var}}, which lint.sh never exits with"
        )

    def test_the_lock_file_step_is_one_of_them(self):
        script = (ROOT / "lint.sh").read_text()
        assert re.search(r"check_lockfiles\s*\|\|\s*STATUS=1", script)


class TestTheLockFileCheck:
    """It had no tests at all (004-F1)."""

    @pytest.fixture
    def repo(self, tmp_path, monkeypatch):
        monkeypatch.setattr(check_lockfiles, "ROOT", tmp_path)
        (tmp_path / "requirements.txt").write_text("fastapi>=0.1\n")
        (tmp_path / "requirements-dev.txt").write_text("pytest\n")
        (tmp_path / "requirements.lock").write_text("fastapi==0.141.1 \\\n    --hash=sha256:x\n")
        (tmp_path / "requirements-dev.lock").write_text(
            "fastapi==0.141.1 \\\n    --hash=sha256:x\npytest==9.1.1 \\\n    --hash=sha256:y\n")
        return tmp_path

    def test_matching_locks_pass(self, repo):
        assert check_lockfiles.main() == 0

    def test_an_unlocked_requirement_fails(self, repo):
        """THE DRIFT 004-F1 REPRODUCED: a package added to requirements.txt
        and never locked."""
        (repo / "requirements.txt").write_text("fastapi>=0.1\ntomli\n")

        assert check_lockfiles.main() == 1

    def test_a_missing_lock_fails(self, repo):
        (repo / "requirements.lock").unlink()

        assert check_lockfiles.main() == 1
