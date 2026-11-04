"""Tests for the thing that checks the tests.

A runner that reported success whatever happened would be worse than
none: it would turn a claim nobody verified into a claim everybody
trusts. So the runner itself gets tested, against controls that break
code it can reach.
"""

import json

import check_controls as cc
import pytest

SUBJECT = "VALUE = 1\n"


def record(control_id="C-1", path="core/old.py", old="VALUE = 1", new="VALUE = 2",
           tests=("a::b",), invariant="none", kind="semantic", describes="a guarantee"):
    lines = [
        "[[control]]",
        f"id = {json.dumps(control_id)}",
        f"describes = {json.dumps(describes)}",
        f"invariant = {json.dumps(invariant)}",
        f"kind = {json.dumps(kind)}",
        f"path = {json.dumps(path)}",
        f"old = {json.dumps(old)}",
        f"new = {json.dumps(new)}",
        f"tests = {json.dumps(list(tests))}",
        'expect = "fails"',
    ]
    return "\n".join(lines) + "\n"


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A small repository in tmp_path; returns a function to add files and controls."""
    monkeypatch.setattr(cc, "ROOT", tmp_path)
    monkeypatch.setattr(cc, "CONTROLS_DIR", tmp_path / "controls")
    monkeypatch.setattr(cc, "SEARCH_ROOTS", ("core", "api"))
    monkeypatch.setattr(cc, "IN_PROGRESS", tmp_path / ".in-progress.json")

    def make(files=None, controls=None):
        for name, text in (files or {}).items():
            target = tmp_path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        for name, text in (controls or {}).items():
            target = tmp_path / "controls" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return tmp_path

    return make


# --- loading ---------------------------------------------------------------

def test_controls_are_loaded_with_their_area_and_card(tree):
    tree(controls={"access/T0.6.toml": record("A-1") + "\n" + record("A-2")})

    controls = cc.load_controls()

    assert [(c.id, c.area, c.card) for c in controls] == [("A-1", "access", "T0.6"), ("A-2", "access", "T0.6")]


@pytest.mark.parametrize("bad", [
    record(kind="vague"),
    record(invariant="I9"),
    record(tests=()),
    record(tests=("a_file_only.py",)),
    record().replace('expect = "fails"', 'expect = "passes"'),
    record().replace('id = "C-1"\n', ""),
    record() + 'surprise = 1\n',
])
def test_a_malformed_record_is_refused(tree, bad):
    tree(controls={"api/X.toml": bad})

    with pytest.raises(ValueError):
        cc.load_controls()


def test_an_id_used_twice_is_refused(tree):
    tree(controls={"api/A.toml": record("C-1"), "api/B.toml": record("C-1")})

    with pytest.raises(ValueError, match="twice"):
        cc.load_controls()


def test_text_survives_the_round_trip_through_a_file(tree):
    tree(controls={"api/A.toml": record(old="a\n    b = 'x'\n", new="")})

    (control,) = cc.load_controls()

    assert control.old == "a\n    b = 'x'\n"
    assert control.new == ""


# --- breaking and running --------------------------------------------------

def test_the_break_is_reverted_even_when_the_tests_fail(tree):
    root = tree({"core/old.py": SUBJECT}, {"api/A.toml": record(tests=("tests/nonexistent.py::x",))})

    cc.main([])

    assert (root / "core/old.py").read_text() == SUBJECT


def test_a_control_that_does_not_fire_is_reported(tree, monkeypatch, capsys):
    tree({"core/old.py": SUBJECT}, {"api/A.toml": record(describes="a guarantee nothing guards")})
    monkeypatch.setattr(cc, "run", lambda control: (cc.SILENT, "1 passed"))

    assert cc.main([]) == 1
    printed = capsys.readouterr().out
    assert "SILENT" in printed
    assert "a guarantee nothing guards" in printed


def test_a_break_that_matches_nothing_stops_the_run(tree):
    tree({"core/old.py": SUBJECT}, {"api/A.toml": record(old="NOT PRESENT")})
    (control,) = cc.load_controls()

    with pytest.raises(SystemExit, match="matches 0 times"):
        cc.apply(control)


def test_a_break_left_by_a_killed_run_is_put_back(tree, capsys):
    root = tree({"core/old.py": "VALUE = 2\n"})
    (root / ".in-progress.json").write_text(json.dumps({"core/old.py": SUBJECT}))

    cc.main(["--summary"])

    assert (root / "core/old.py").read_text() == SUBJECT
    assert not (root / ".in-progress.json").exists()
    assert "restored core/old.py" in capsys.readouterr().out


def test_the_original_is_parked_before_the_break_goes_in(tree):
    root = tree({"core/old.py": SUBJECT}, {"api/A.toml": record()})
    (control,) = cc.load_controls()

    cc.apply(control)

    assert (root / "core/old.py").read_text() == "VALUE = 2\n"
    assert json.loads((root / ".in-progress.json").read_text()) == {"core/old.py": SUBJECT}


def test_an_unreadable_record_shouts_rather_than_carrying_on(tree):
    root = tree()
    (root / ".in-progress.json").write_text("{not json")

    with pytest.raises(SystemExit, match="unreadable"):
        cc.restore_anything_left_behind()


@pytest.mark.parametrize("code,expected", [
    (1, "fires"), (0, "silent"),
    (2, "broken"), (3, "broken"), (4, "broken"), (5, "broken"), (99, "broken"),
])
def test_only_a_failed_test_counts_as_firing(code, expected):
    outcome, why = cc.classify(code)

    assert outcome == expected
    assert str(code) in why or code in (0, 1)


def test_a_control_citing_a_missing_test_is_broken_not_firing(tree, capsys):
    tree({"core/old.py": SUBJECT, "test_subject.py": "def test_real():\n    assert True\n"},
         {"api/A.toml": record(tests=("test_subject.py::test_that_does_not_exist",))})

    assert cc.main([]) == 1
    printed = capsys.readouterr().out
    assert "BROKEN" in printed
    assert "fires " not in printed
    assert "exited 4" in printed


def test_a_control_whose_tests_were_all_skipped_is_broken_not_silent(tree, capsys):
    tree({"core/old.py": SUBJECT,
          "test_subject.py": "import pytest\n\n@pytest.mark.skip(reason='no server')\n"
                             "def test_it():\n    assert False\n"},
         {"api/A.toml": record(tests=("test_subject.py::test_it",))})

    assert cc.main([]) == 1
    printed = capsys.readouterr().out
    assert "BROKEN" in printed
    assert "skipped" in printed
    assert "SILENT" not in printed


def test_a_control_that_makes_its_test_fail_fires(tree, capsys):
    tree({"core/old.py": SUBJECT,
          "test_subject.py": "from pathlib import Path\n\n"
                             "def test_it():\n    assert 'VALUE = 1' in Path('core/old.py').read_text()\n"},
         {"api/A.toml": record(tests=("test_subject.py::test_it",))})

    assert cc.main([]) == 0
    assert "fires   C-1" in capsys.readouterr().out


# --- selection ---------------------------------------------------------------

def test_card_area_and_kind_select_controls(tree, monkeypatch, capsys):
    tree({"core/old.py": SUBJECT, "core/two.py": "OTHER = 1\n"},
         {"api/T0.5.toml": record("A-1"),
          "state/T0.7.toml": record("S-1", path="core/two.py", old="OTHER = 1", new="OTHER = 2",
                                    kind="mechanical")})
    fired = []
    monkeypatch.setattr(cc, "run", lambda control: fired.append(control.id) or (cc.FIRES, ""))

    cc.main(["--card", "T0.7"])
    cc.main(["--area", "api"])
    cc.main(["--kind", "mechanical"])

    assert fired == ["S-1", "A-1", "S-1"]


def test_a_card_without_controls_passes_and_says_so(tree, capsys):
    tree(controls={"api/T0.5.toml": record()})

    assert cc.main(["--card", "T0.9"]) == 0
    assert "has no controls" in capsys.readouterr().out


# --- content anchoring -------------------------------------------------------

def control(path="core/old.py", old="VALUE = 1"):
    return cc.Control(id="C-1", invariant="none", kind="semantic", path=path, old=old,
                      new="VALUE = 2", tests=["a::b"])


def test_an_anchor_still_in_its_file_is_ok(tree):
    tree({"core/old.py": SUBJECT})

    assert cc.resolve(control()) == (cc.OK, ["core/old.py"])


def test_an_anchor_that_moved_to_one_file_is_moved(tree):
    tree({"core/old.py": "pass\n", "core/new/home.py": SUBJECT, "core/other.py": "unrelated\n"})

    assert cc.resolve(control()) == (cc.MOVED, ["core/new/home.py"])


def test_an_anchor_that_vanished_is_retired(tree):
    tree({"core/old.py": "pass\n", "api/x.py": "pass\n"})

    assert cc.resolve(control()) == (cc.RETIRED, [])


def test_an_anchor_in_several_files_is_ambiguous(tree):
    tree({"core/old.py": "pass\n", "core/a.py": SUBJECT, "api/b.py": SUBJECT})

    assert cc.resolve(control()) == (cc.AMBIGUOUS, ["api/b.py", "core/a.py"])


def test_an_anchor_twice_in_one_other_file_is_ambiguous(tree):
    tree({"core/old.py": "pass\n", "core/a.py": SUBJECT * 2})

    assert cc.resolve(control())[0] == cc.AMBIGUOUS


def test_only_the_governed_tree_is_searched(tree):
    tree({"core/old.py": "pass\n", "docs/notes.py": SUBJECT, "core/node_modules/x.py": SUBJECT})

    assert cc.resolve(control())[0] == cc.RETIRED


def test_a_moved_control_runs_against_its_new_file_but_does_not_count_as_firing(tree, monkeypatch, capsys):
    root = tree({"core/old.py": "pass\n", "core/new.py": SUBJECT}, {"api/A.toml": record()})
    monkeypatch.setattr(cc, "run", lambda c: (cc.FIRES, "1 failed"))

    assert cc.main([]) == 1
    printed = capsys.readouterr().out
    assert "MOVED" in printed and "core/new.py" in printed
    assert "fires " not in printed
    assert (root / "core/new.py").read_text() == SUBJECT


def test_retired_and_ambiguous_controls_are_not_run_and_fail_the_run(tree, monkeypatch, capsys):
    tree({"core/old.py": "pass\n"}, {"api/A.toml": record(describes="gone")})
    ran = []
    monkeypatch.setattr(cc, "run", lambda c: ran.append(c) or (cc.FIRES, ""))

    assert cc.main([]) == 1
    printed = capsys.readouterr().out
    assert "RETIRED" in printed and "gone" in printed
    assert not ran
    assert "fires " not in printed


def test_report_moves_prints_and_runs_nothing(tree, monkeypatch, capsys):
    tree({"core/old.py": "pass\n", "core/new.py": SUBJECT}, {"api/A.toml": record()})
    monkeypatch.setattr(cc, "run", lambda c: pytest.fail("must not run"))

    assert cc.main(["--report-moves"]) == 1
    assert "core/old.py -> core/new.py" in capsys.readouterr().out


def test_rewrite_paths_changes_only_the_path_of_moved_controls(tree):
    text = record("C-1", path="core/a.py") + "\n" + record("C-2", path="core/a.py")

    rewritten, count = cc.rewrite_paths(text, {"C-1": "src/b.py"})

    assert count == 1
    assert rewritten == text.replace('path = "core/a.py"', 'path = "src/b.py"', 1)


def test_rewrite_paths_option_updates_the_file_it_lives_in(tree):
    root = tree({"core/old.py": "pass\n", "core/new.py": SUBJECT}, {"api/A.toml": record()})

    assert cc.main(["--rewrite-paths"]) == 0
    assert 'path = "core/new.py"' in (root / "controls/api/A.toml").read_text()
    assert cc.main(["--report-moves"]) == 0


# --- reports -----------------------------------------------------------------

def test_summary_counts_and_runs_nothing(tree, monkeypatch, capsys):
    tree({"core/old.py": SUBJECT}, {"api/A.toml": record("A-1") + "\n" + record("A-2", kind="mechanical")})
    monkeypatch.setattr(cc, "run", lambda c: pytest.fail("must not run"))

    assert cc.main(["--summary"]) == 0
    printed = capsys.readouterr().out
    assert "controls: 2" in printed
    assert "mechanical   1" in printed
    assert "ok           2" in printed


def test_coverage_fails_while_an_invariant_has_no_live_control(tree, capsys):
    tree({"core/old.py": SUBJECT}, {"api/A.toml": record(invariant="I3")})

    assert cc.main(["--coverage"]) == 1
    printed = capsys.readouterr().out
    assert "I3     1 live control(s)" in printed
    assert "I1     0 live control(s)   <-- none" in printed


def test_coverage_passes_when_every_invariant_has_one(tree):
    controls = "\n".join(record(f"C-{n}", invariant=f"I{n}") for n in range(1, 9))
    tree({"core/old.py": SUBJECT}, {"api/A.toml": controls})

    assert cc.main(["--coverage"]) == 0


def test_a_retired_control_does_not_count_toward_coverage(tree):
    controls = "\n".join(record(f"C-{n}", invariant=f"I{n}") for n in range(1, 9))
    tree({"core/old.py": "pass\n"}, {"api/A.toml": controls})

    assert cc.main(["--coverage"]) == 1
