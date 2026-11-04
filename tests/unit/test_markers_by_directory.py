"""Markers come from the directory a test lives in (N58, N91)."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
CONFTEST = ROOT / "tests" / "conftest.py"

TREE = {
    "tests/unit/test_a.py": "fast",
    "tests/cli/test_b.py": "fast",
    "tests/property/test_c.py": "fast",
    "tests/api/test_d.py": "api",
    "tests/integration/test_e.py": "lake",
    "tests/foo/contract/test_f.py": "fast",
    "tests/foo/e2e/test_g.py": "lake",
    "tests/foo/fuzz/test_h.py": "fuzz",
    "tests/api/fuzz/test_i.py": "fuzz",
    "tests/unit/fuzz/test_j.py": "fuzz",
    "tests/api/contract/test_k.py": "fast",
    "tests/elsewhere/test_l.py": None,
}


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    """A small project whose tests/conftest.py is the real one."""
    root = tmp_path_factory.mktemp("marked")
    (root / "pytest.ini").write_text("[pytest]\nmarkers =\n    live: slow\n    fast: x\n    api: x\n    lake: x\n"
                                     "    fuzz: x\n")
    (root / "tests").mkdir()
    shutil.copy(CONFTEST, root / "tests" / "conftest.py")
    for name in TREE:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_it():\n    assert True\n")
    live = root / "tests" / "unit" / "test_live.py"
    live.write_text("import pytest\n\n@pytest.mark.live\ndef test_it():\n    assert True\n")
    return root


def collected(tree: Path, marker: str) -> set[str]:
    result = subprocess.run(  # noqa: S603 -- our own interpreter
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-m", marker],
        cwd=tree, capture_output=True, text=True, check=False)
    return {line.split("::")[0] for line in result.stdout.splitlines() if "::" in line}


@pytest.mark.parametrize("marker", ["fast", "api", "lake", "fuzz"])
def test_each_directory_gets_its_marker(tree, marker):
    expected = {name for name, mark in TREE.items() if mark == marker}

    assert collected(tree, marker) == expected


def test_a_test_marked_live_keeps_only_live(tree):
    assert collected(tree, "live") == {"tests/unit/test_live.py"}
    assert "tests/unit/test_live.py" not in collected(tree, "fast")


def test_a_directory_without_a_rule_gets_no_marker(tree):
    marked = set().union(*(collected(tree, m) for m in ("fast", "api", "lake", "fuzz")))

    assert "tests/elsewhere/test_l.py" not in marked


def test_the_most_specific_directory_wins():
    spec = importlib.util.spec_from_file_location("real_conftest", CONFTEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.marker_for_directory(("api", "fuzz")) == "fuzz"
    assert module.marker_for_directory(("foo", "fuzz")) == "fuzz"
    assert module.marker_for_directory(("api",)) == "api"
    assert module.marker_for_directory(("contract",)) is None
    assert module.marker_for_directory(()) is None


def test_the_markers_are_registered():
    text = (ROOT / "pytest.ini").read_text()

    for name in ("fast", "api", "lake", "fuzz", "live"):
        assert f"\n    {name}:" in text


def test_the_full_run_uses_the_hypothesis_profile(tree):
    (tree / "tests" / "foo" / "fuzz" / "test_profile.py").write_text(
        "from hypothesis import settings\n\n"
        "def test_profile():\n    assert settings().max_examples == 100 and settings().derandomize\n")

    result = subprocess.run(  # noqa: S603 -- our own interpreter
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--hypothesis-profile=full",
         "tests/foo/fuzz/test_profile.py"],
        cwd=tree, capture_output=True, text=True, check=False)

    assert result.returncode == 0, result.stdout
