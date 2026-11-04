"""The lock-file check fails on drift (it had no tests once, and drift passed)."""

import pytest

import elysium.scripts.check_lockfiles as check_lockfiles


class TestTheLockFileCheck:
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
        (repo / "requirements.txt").write_text("fastapi>=0.1\ntomli\n")

        assert check_lockfiles.main() == 1

    def test_a_missing_lock_fails(self, repo):
        (repo / "requirements.lock").unlink()

        assert check_lockfiles.main() == 1
