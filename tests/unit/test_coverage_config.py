"""Coverage is configured: branch coverage of the package, measured only."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def coverage_run(pyproject):
    return pyproject.get("tool", {}).get("coverage", {}).get("run", {})


def is_configured(pyproject):
    run = coverage_run(pyproject)
    return run.get("branch") is True and run.get("source") == ["src/elysium"]


def test_the_repository_measures_branch_coverage_of_the_package():
    assert is_configured(tomllib.loads((ROOT / "pyproject.toml").read_text()))


def test_the_check_fails_without_the_config():
    assert not is_configured({})
    assert not is_configured({"tool": {"coverage": {"run": {"branch": False, "source": ["src/elysium"]}}}})
    assert not is_configured({"tool": {"coverage": {"run": {"branch": True}}}})
