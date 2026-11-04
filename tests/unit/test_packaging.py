"""Dependencies live in pyproject.toml and uv.lock, and nowhere else."""

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_the_build_backend_is_hatchling_with_vcs_versions():
    assert PYPROJECT["build-system"]["build-backend"] == "hatchling.build"
    assert any(r.startswith("hatch-vcs") for r in PYPROJECT["build-system"]["requires"])
    assert PYPROJECT["project"]["dynamic"] == ["version"]


@pytest.mark.parametrize("extra", ["identity", "tui", "dev"])
def test_the_extras_exist(extra):
    assert PYPROJECT["project"]["optional-dependencies"][extra]


def test_runtime_dependencies_are_declared_and_bounded():
    dependencies = PYPROJECT["project"]["dependencies"]
    assert any(d.startswith("fastapi") for d in dependencies)
    assert not any(d.startswith(("pytest", "ruff", "mypy")) for d in dependencies)


@pytest.mark.parametrize(
    "gone",
    [
        "requirements.txt",
        "requirements.lock",
        "requirements-dev.txt",
        "requirements-dev.lock",
        "src/elysium/scripts/check_lockfiles.py",
    ],
)
def test_the_hand_synchronised_files_are_gone(gone):
    assert not (ROOT / gone).exists()


def test_the_lock_exists():
    assert (ROOT / "uv.lock").is_file()
