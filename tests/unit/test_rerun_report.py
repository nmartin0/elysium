"""rerun_report runs the claimed commands again and compares the exit statuses."""

import os
import stat

import pytest
import rerun_report

REPORT = """REPORT
1. Card X, DONE.
2. Branch card/X.
3. Every command run:
   `echo hello` -> exit 0
     hello
   - `bash -c 'exit 3'` -> exit 3
   `false` -> exit 1
4. Controls added: none. `ignored` -> exit 9
"""


@pytest.fixture
def heavy(tmp_path):
    """A stand-in for tools/heavy.sh: NAME CMD... run, status passed on."""
    script = tmp_path / "heavy.sh"
    script.write_text('#!/usr/bin/env bash\nshift\n"$@"\n')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_the_claims_of_section_3_are_read_and_nothing_else():
    assert rerun_report.claims(REPORT) == [("echo hello", 0), ("bash -c 'exit 3'", 3), ("false", 1)]


def test_a_report_without_section_3_has_no_claims():
    assert rerun_report.claims("REPORT\n1. x\n2. y\n") == []


def test_matching_statuses_exit_0(tmp_path, heavy, capsys):
    report = tmp_path / "r.md"
    report.write_text(REPORT)

    assert rerun_report.main([str(report), "--worktree", str(tmp_path), "--heavy", str(heavy)]) == 0
    out = capsys.readouterr().out
    assert "command" in out and "claimed" in out and "actual" in out
    assert "DIFFERS" not in out


def test_a_difference_exits_1_and_is_marked(tmp_path, heavy, capsys):
    report = tmp_path / "r.md"
    report.write_text(REPORT.replace("`false` -> exit 1", "`false` -> exit 0"))

    assert rerun_report.main([str(report), "--worktree", str(tmp_path), "--heavy", str(heavy)]) == 1
    line = next(x for x in capsys.readouterr().out.splitlines() if x.startswith("false"))
    assert line.endswith("DIFFERS")


def test_the_command_runs_in_the_worktree(tmp_path, heavy):
    work = tmp_path / "wt"
    work.mkdir()
    (work / "marker").write_text("x")
    report = tmp_path / "r.md"
    report.write_text("3. commands\n   `test -f marker` -> exit 0\n4. end\n")

    assert rerun_report.main([str(report), "--worktree", str(work), "--heavy", str(heavy)]) == 0
    assert os.path.exists(work / "marker")


def test_an_empty_report_exits_1(tmp_path, heavy, capsys):
    report = tmp_path / "r.md"
    report.write_text("nothing here\n")

    assert rerun_report.main([str(report), "--heavy", str(heavy)]) == 1
    assert "no command" in capsys.readouterr().err
