"""Strict typing: by package glob for new code, by list for legacy modules (N38, N59)."""

import shutil
import subprocess
import tomllib
from pathlib import Path

import mypy_strict as strict
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
GLOBS = [
    "elysium.access.*", "elysium.query.*", "elysium.actions.*", "elysium.proposals.*", "elysium.metadata.*",
    "elysium.resources.*", "elysium.db.*", "elysium.audit.*", "elysium.jobs.*", "elysium.runner.*",
    "elysium.ops.*", "elysium.exports.*", "elysium.cli.*", "elysium.erasure.*", "elysium.index.*",
    "elysium.datasets.*", "elysium.connectivity.*", "elysium.automation.*", "elysium.checks.*",
    "elysium.agent.*", "elysium.apps.*", "elysium.keys.*", "elysium.functions.*", "elysium.service.*",
    "elysium.builtin.*", "elysium.settings", "elysium.paths", "elysium.paging", "elysium.secrets",
    "elysium.errors", "elysium.bootstrap", "elysium.logging_json", "elysium.api.v2.*",
]


def overrides():
    return PYPROJECT["tool"]["mypy"]["overrides"]


def test_the_glob_block_lists_every_package_of_the_layer_table():
    (block,) = [o for o in overrides() if "elysium.access.*" in o["module"]]

    assert block["module"] == GLOBS


def test_the_glob_block_turns_on_what_strict_turns_on():
    (block,) = [o for o in overrides() if "elysium.access.*" in o["module"]]

    assert {name for name in strict.STRICT_OPTIONS} <= set(block)
    assert all(block[name] is True for name in strict.STRICT_OPTIONS)


def test_mypy_files_include_tests_without_checking_untyped_test_bodies():
    assert "tests" in PYPROJECT["tool"]["mypy"]["files"]
    (tests,) = [o for o in overrides() if o["module"] == ["tests.*"]]
    assert tests["check_untyped_defs"] is False


@pytest.fixture
def project(tmp_path):
    """A copy of the mypy configuration with a package under src/."""
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    package = tmp_path / "src" / "elysium" / "access"
    package.mkdir(parents=True)
    (tmp_path / "src" / "elysium" / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    return tmp_path


def run_mypy(project, module_file):
    return subprocess.run(  # noqa: S603, S607 -- fixed command
        ["mypy", "--no-incremental", "--cache-dir", str(project / ".cache"), str(module_file)],  # noqa: S607 -- fixed command
        capture_output=True, text=True, check=False, cwd=project)


def test_a_new_module_in_a_strict_package_must_be_typed(project):
    module = project / "src" / "elysium" / "access" / "grants.py"
    module.write_text("def allowed(user, thing):\n    return True\n")

    result = run_mypy(project, module)

    assert result.returncode == 1
    assert "no-untyped-def" in result.stdout


def test_the_same_module_outside_the_globs_is_not_strict(project):
    other = project / "src" / "elysium" / "scratch"
    other.mkdir()
    (other / "__init__.py").write_text("")
    module = other / "grants.py"
    module.write_text("def allowed(user, thing):\n    return True\n")

    assert run_mypy(project, module).returncode == 0


def test_removing_a_package_from_the_glob_list_lets_untyped_code_through(project):
    text = (project / "pyproject.toml").read_text().replace('"elysium.access.*", ', "", 1)
    (project / "pyproject.toml").write_text(text)
    module = project / "src" / "elysium" / "access" / "grants.py"
    module.write_text("def allowed(user, thing):\n    return True\n")

    assert run_mypy(project, module).returncode == 0


def test_the_strict_list_has_not_lost_a_module():
    listed = set(strict.listed())
    head = subprocess.run(  # noqa: S603, S607 -- fixed command
        ["git", "show", "HEAD:quality/strict-modules.txt"],  # noqa: S607 -- fixed command
        capture_output=True, text=True, check=False, cwd=ROOT)
    if head.returncode != 0:
        pytest.skip("the list is not committed yet")
    committed = {line for line in head.stdout.splitlines() if line.strip() and not line.startswith("#")}

    assert committed <= listed, f"removed from the strict list: {sorted(committed - listed)}"


def test_the_generated_block_is_the_list_and_every_listed_module_is_clean():
    assert strict.main(["--check"]) == 0


def test_the_list_holds_only_legacy_modules():
    assert all(m.startswith(("elysium.core", "elysium.api")) for m in strict.listed())
    assert not any(m.startswith("elysium.api.v2") for m in strict.listed())


def test_a_listed_module_with_an_error_fails_the_check(monkeypatch):
    monkeypatch.setattr(strict, "errors_with", lambda modules, text: {modules[0]})

    assert strict.main(["--check"]) == 1


def test_module_names():
    assert strict.module_of("src/elysium/core/x.py") == "elysium.core.x"
    assert strict.module_of("src/elysium/core/__init__.py") == "elysium.core"
