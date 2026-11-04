"""The ruff baseline only shrinks, and the rules it covers are live."""

import subprocess
import textwrap
from pathlib import Path

import ruff_baseline as baseline

ROOT = Path(__file__).resolve().parent.parent.parent


def test_the_generated_list_has_not_gained_an_entry():
    assert baseline.main(["--check"]) == 0


def test_a_new_offence_in_a_listed_file_is_a_gain():
    listed = baseline.read_baseline()
    path, rule = next(iter(listed))
    current = dict(listed)
    current[(path, rule)] += 1

    assert baseline.gained(current, listed) == [f"{path} {rule}: {listed[(path, rule)] + 1} found, "
                                                f"{listed[(path, rule)]} listed"]


def test_an_offence_in_an_unlisted_file_is_a_gain():
    assert baseline.gained({("src/elysium/new_module.py", "BLE001"): 1}, baseline.read_baseline())


def test_fewer_offences_are_not_a_gain():
    listed = baseline.read_baseline()
    path, rule = next(iter(listed))

    assert baseline.gained({(path, rule): 0}, listed) == []


def test_the_block_in_pyproject_must_be_the_list(monkeypatch):
    monkeypatch.setattr(baseline, "read_baseline", lambda: {("src/elysium/x.py", "S101"): 1})
    monkeypatch.setattr(baseline, "offenders", lambda: {})

    assert baseline.main(["--check"]) == 1


def test_a_new_broad_except_is_found_by_the_repository_config(tmp_path):
    source = tmp_path / "broad.py"
    source.write_text(textwrap.dedent("""\
        def f():
            try:
                return 1
            except Exception:
                return 2
        """))

    result = subprocess.run(  # noqa: S603, S607 -- fixed command
        ["ruff", "check", "--config", str(ROOT / "pyproject.toml"), "--select", "BLE", str(source)],  # noqa: S607 -- fixed command
        capture_output=True, text=True, check=False)

    assert result.returncode == 1
    assert "BLE001" in result.stdout


def test_a_justified_broad_except_is_live_and_passes(tmp_path):
    source = tmp_path / "broad.py"
    source.write_text("def f():\n    try:\n        return 1\n"
                      "    except Exception:  # noqa: BLE001 -- the rule\n        return 2\n")

    result = subprocess.run(  # noqa: S603, S607 -- fixed command
        ["ruff", "check", "--config", str(ROOT / "pyproject.toml"), "--select", "BLE", str(source)],  # noqa: S607 -- fixed command
        capture_output=True, text=True, check=False)

    assert result.returncode == 0


def test_the_rules_are_selected_and_complexity_is_fifteen():
    import tomllib

    lint = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["ruff"]["lint"]

    assert {"BLE", "S", "C901"} <= set(lint["select"])
    assert lint["mccabe"]["max-complexity"] == 15
