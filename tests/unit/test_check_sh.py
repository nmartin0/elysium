"""check.sh runs every step, fails when any step fails, and says so."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def run_check(tmp_path: Path, steps: list[tuple[str, str]], *args: str):
    steps_file = tmp_path / "steps.tsv"
    steps_file.write_text("".join(f"{name}\t{cmd}\n" for name, cmd in steps))
    return subprocess.run(
        ["bash", str(ROOT / "check.sh"), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "CHECK_SH_STEPS_FILE": str(steps_file)},
        check=False,
    )


def test_failing_step_fails_the_run(tmp_path):
    result = run_check(tmp_path, [("piped", "(echo out; exit 3) | cat")])

    assert result.returncode != 0
    assert "piped | 3 |" in result.stdout


def test_summary_lists_every_step(tmp_path):
    result = run_check(
        tmp_path,
        [("first", "exit 1"), ("second", "true"), ("third", "exit 2")],
    )

    assert result.returncode == 1
    for line in ("first | 1 |", "second | 0 |", "third | 2 |"):
        assert line in result.stdout


def test_all_steps_passing_exits_zero(tmp_path):
    result = run_check(tmp_path, [("a", "true"), ("b", "true")])

    assert result.returncode == 0


def test_an_unknown_flag_is_refused(tmp_path):
    result = run_check(tmp_path, [("a", "true")], "--nope")

    assert result.returncode == 2


def test_every_built_in_step_can_fail_the_script():
    """Source tripwire: a step is run through `step`, whose status is the
    one the script exits with; nothing may run a gate outside it."""
    script = (ROOT / "check.sh").read_text()

    assert 'exit "$failed"' in script
    assert script.count("set -uo pipefail") == 1
    assert "|| true" in script  # only the report-only diffsize step
    assert script.count("|| true") == 1


def test_an_area_runs_only_that_areas_controls(tmp_path):
    result = subprocess.run(
        ["bash", str(ROOT / "check.sh"), "--area", "nonesuch"],
        capture_output=True, text=True, check=False)

    assert result.returncode == 1
    assert "controls:nonesuch | 1 |" in result.stdout
    assert "ruff" not in result.stdout


def test_area_needs_a_name():
    result = subprocess.run(["bash", str(ROOT / "check.sh"), "--area"], capture_output=True, text=True, check=False)

    assert result.returncode == 2
