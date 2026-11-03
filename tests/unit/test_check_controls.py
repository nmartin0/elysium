"""Tests for the thing that checks the tests.

A runner that reported success whatever happened would be worse than
none: it would turn a claim nobody verified into a claim everybody
trusts. So the runner itself gets tested, against controls that break
code it can reach.
"""

import pytest

from elysium.scripts.check_controls import CONTROLS, Control, apply, main


def test_every_declared_break_matches_exactly_once():
    # A break that matches nothing runs the UNMODIFIED code and passes,
    # which has happened by hand in this project more than once. It is
    # the failure mode this whole script exists to catch, so it cannot
    # be allowed in the script's own declarations.
    #
    # The anchor is the text, not the path: a break that now lives in
    # another file still matches exactly once, and fails here only so
    # that the stale path is seen -- with the one-command fix in the
    # message.
    from elysium.scripts.check_controls import AMBIGUOUS, MOVED, OK, RETIRED, resolve_all

    resolved = resolve_all(CONTROLS)
    moved = [f"  {c.path} -> {p[0]}  ({c.describes})" for c, s, p in resolved if s == MOVED]
    lost = [f"  {c.path}: {s}  ({c.describes})"
            for c, s, p in resolved if s in (RETIRED, AMBIGUOUS)]
    assert all(s in (OK, MOVED, RETIRED, AMBIGUOUS) for _, s, _ in resolved)
    message = []
    if moved:
        message.append(f"{len(moved)} control(s) MOVED; run "
                       f"`python scripts/check_controls.py --rewrite-paths`:\n" + "\n".join(moved))
    if lost:
        message.append("controls whose break matches nothing or too much:\n" + "\n".join(lost))
    assert not message, "\n".join(message)


def test_every_control_names_the_tests_it_expects_to_fail():
    for control in CONTROLS:
        assert control.tests, control.describes
        # Individual tests, not whole files: a control that fires for
        # an unrelated reason should be visible as the wrong test
        # failing.
        assert all("::" in name for name in control.tests), control.tests


def test_the_break_is_reverted_even_when_the_tests_fail(tmp_path, monkeypatch):
    # A broken file left behind would look like a bug in the code
    # rather than in this script, and would be found by somebody else,
    # later, confused.
    from elysium.scripts import check_controls

    target = tmp_path / "subject.py"
    target.write_text("VALUE = 1\n")
    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    monkeypatch.setattr(check_controls, "CONTROLS", [
        Control(describes="a made-up guarantee", path="subject.py",
                old="VALUE = 1", new="VALUE = 2", tests=["tests/nonexistent.py::x"]),
    ])

    main([])
    assert target.read_text() == "VALUE = 1\n"


def test_a_control_that_does_not_fire_is_reported(tmp_path, monkeypatch, capsys):
    # THE point. A control that passes means either the break is not
    # the break it claims or the tests do not check what they appear
    # to -- and in this project it has been the second nine times out
    # of ten.
    from elysium.scripts import check_controls

    target = tmp_path / "subject.py"
    target.write_text("VALUE = 1\n")
    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    monkeypatch.setattr(check_controls, "CONTROLS", [
        Control(describes="a guarantee nothing guards", path="subject.py",
                old="VALUE = 1", new="VALUE = 2", tests=[]),
    ])
    # No tests named, so pytest exits zero and the control is silent.
    monkeypatch.setattr(check_controls, "run", lambda control: (check_controls.SILENT, "1 passed"))

    assert main([]) == 1
    printed = capsys.readouterr().out
    assert "SILENT" in printed
    assert "a guarantee nothing guards" in printed


def test_a_break_that_matches_nothing_stops_the_run(tmp_path, monkeypatch):
    from elysium.scripts import check_controls

    (tmp_path / "subject.py").write_text("VALUE = 1\n")
    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    control = Control(describes="a break that is not there", path="subject.py",
                      old="NOT PRESENT", new="x", tests=["a::b"])
    with pytest.raises(SystemExit, match="matches 0 times"):
        apply(control)


def test_there_are_controls_to_run():
    # A list that has quietly emptied would pass every assertion above.
    assert len(CONTROLS) >= 10
    assert len({control.describes for control in CONTROLS}) == len(CONTROLS)


def test_a_break_left_by_a_killed_run_is_put_back(tmp_path, monkeypatch, capsys):
    # THE failure this survived once already. The `finally` that
    # restores a break cannot help if the process is KILLED -- a run
    # inside a command that hit its time limit was killed mid-control
    # and left a break in the working tree, where it sat until a later
    # run reported "the break matches 0 times".
    import json

    from elysium.scripts import check_controls

    subject = tmp_path / "subject.py"
    subject.write_text("VALUE = 2\n")            # as the break left it
    parked = tmp_path / ".controls-in-progress.json"
    parked.write_text(json.dumps({"subject.py": "VALUE = 1\n"}))

    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    monkeypatch.setattr(check_controls, "IN_PROGRESS", parked)
    monkeypatch.setattr(check_controls, "CONTROLS", [])

    check_controls.main([])
    assert subject.read_text() == "VALUE = 1\n"
    assert not parked.exists(), "the record was left behind after restoring"
    assert "restored subject.py" in capsys.readouterr().out


def test_the_original_is_parked_before_the_break_goes_in(tmp_path, monkeypatch):
    # Before, not after: a kill BETWEEN the two would otherwise leave
    # the file broken with no record of what it was.
    import json

    from elysium.scripts import check_controls

    subject = tmp_path / "subject.py"
    subject.write_text("VALUE = 1\n")
    parked = tmp_path / ".controls-in-progress.json"
    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    monkeypatch.setattr(check_controls, "IN_PROGRESS", parked)

    check_controls.apply(Control(describes="x", path="subject.py",
                                 old="VALUE = 1", new="VALUE = 2", tests=["a::b"]))
    assert subject.read_text() == "VALUE = 2\n"
    assert json.loads(parked.read_text()) == {"subject.py": "VALUE = 1\n"}


def test_an_unreadable_record_shouts_rather_than_carrying_on(tmp_path, monkeypatch):
    # Something is in the tree and this cannot say what. Better to
    # stop than to run a suite against code nobody meant to change.
    from elysium.scripts import check_controls

    parked = tmp_path / ".controls-in-progress.json"
    parked.write_text("{not json")
    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    monkeypatch.setattr(check_controls, "IN_PROGRESS", parked)

    with pytest.raises(SystemExit, match="unreadable"):
        check_controls.restore_anything_left_behind()


@pytest.mark.parametrize("code,expected", [
    (1, "fires"), (0, "silent"),
    (2, "broken"), (3, "broken"), (4, "broken"), (5, "broken"), (99, "broken"),
])
def test_only_a_failed_test_counts_as_firing(code, expected):
    # Exit 4 (a test id not found) and 2 (collection broken by the
    # break) used to count as "fires" because the runner asked only
    # whether the status was non-zero.
    from elysium.scripts.check_controls import classify

    outcome, why = classify(code)
    assert outcome == expected
    assert str(code) in why or code in (0, 1)


def test_a_control_citing_a_missing_test_is_broken_not_firing(tmp_path, monkeypatch, capsys):
    # End to end through the real pytest: the id does not exist, pytest
    # exits 4, and the run must say so and fail.
    from elysium.scripts import check_controls

    (tmp_path / "subject.py").write_text("VALUE = 1\n")
    (tmp_path / "test_subject.py").write_text("def test_real():\n    assert True\n")
    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    monkeypatch.setattr(check_controls, "IN_PROGRESS", tmp_path / ".in-progress.json")
    monkeypatch.setattr(check_controls, "CONTROLS", [
        Control(describes="cites a test that is not there", path="subject.py",
                old="VALUE = 1", new="VALUE = 2",
                tests=["test_subject.py::test_that_does_not_exist"]),
    ])

    assert check_controls.main([]) == 1
    printed = capsys.readouterr().out
    assert "BROKEN" in printed
    assert "fires " not in printed
    assert "exited 4" in printed


def _resolves(test_id: str) -> str | None:
    """None if the id names something that exists, else why not.

    By AST rather than by running pytest, so checking every id costs
    milliseconds: the file exists, and each `::` part is a function or
    class defined (nested for the parts after the first) in it. A
    parametrization suffix `[...]` is dropped, since it is chosen at
    collection.
    """
    import ast
    import re

    from elysium.scripts.check_controls import ROOT

    path, *parts = test_id.split("::")
    if not parts:
        return "no ::name"
    parts[-1] = re.sub(r"\[.*\]$", "", parts[-1])
    file = ROOT / path
    if not file.is_file():
        return f"{path} does not exist"
    body = ast.parse(file.read_text()).body
    for name in parts:
        found = next((node for node in body
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and node.name == name), None)
        if found is None:
            return f"{name} is not defined in {path}" + (
                "" if name is parts[0] else " at that nesting")
        body = found.body
    return None


def test_every_test_a_control_cites_exists():
    # The check the runner could not make: that the break is guarded by
    # tests that are really there.
    missing = [f"{control.describes!r}: {test_id} ({why})"
               for control in CONTROLS for test_id in control.tests
               if (why := _resolves(test_id)) is not None]
    assert not missing, "controls citing tests that do not exist:\n" + "\n".join(missing)


def test_the_resolver_notices_a_missing_function_class_and_file():
    # Its own control: a resolver that answered None for everything
    # would make the test above pass for ever.
    assert _resolves("tests/unit/test_check_controls.py::test_there_are_controls_to_run") is None
    assert _resolves("tests/unit/test_check_controls.py::test_nothing_of_the_kind") is not None
    assert _resolves("tests/unit/test_check_controls.py::NoSuchClass::test_x") is not None
    assert _resolves("tests/unit/no_such_file.py::test_x") is not None
    assert _resolves("tests/unit/test_check_controls.py") is not None


def test_a_control_whose_tests_were_all_skipped_is_broken_not_silent(tmp_path, monkeypatch, capsys):
    # Exit status 0, but nothing ran: the code was not shown to be
    # noticed OR missed.
    from elysium.scripts import check_controls

    (tmp_path / "subject.py").write_text("VALUE = 1\n")
    (tmp_path / "test_subject.py").write_text(
        "import pytest\n\n@pytest.mark.skip(reason='no server')\ndef test_it():\n    assert False\n")
    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    monkeypatch.setattr(check_controls, "IN_PROGRESS", tmp_path / ".in-progress.json")
    monkeypatch.setattr(check_controls, "CONTROLS", [
        Control(describes="guarded by a skipped test", path="subject.py",
                old="VALUE = 1", new="VALUE = 2", tests=["test_subject.py::test_it"]),
    ])

    assert check_controls.main([]) == 1
    printed = capsys.readouterr().out
    assert "BROKEN" in printed
    assert "skipped" in printed
    assert "SILENT" not in printed


# --- content anchoring, against a small temporary tree -----------------

def _tree(tmp_path, monkeypatch, files):
    from elysium.scripts import check_controls

    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    monkeypatch.setattr(check_controls, "ROOT", tmp_path)
    monkeypatch.setattr(check_controls, "SEARCH_ROOTS", ("core", "api"))
    monkeypatch.setattr(check_controls, "IN_PROGRESS", tmp_path / ".in-progress.json")
    return check_controls


def _control(path="core/old.py", old="VALUE = 1", describes="a guarantee"):
    return Control(describes=describes, path=path, old=old, new="VALUE = 2", tests=["a::b"])


def test_an_anchor_still_in_its_file_is_ok(tmp_path, monkeypatch):
    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "VALUE = 1\n"})
    assert cc.resolve(_control()) == (cc.OK, ["core/old.py"])


def test_an_anchor_that_moved_to_one_file_is_moved(tmp_path, monkeypatch):
    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "pass\n",
                                       "core/new/home.py": "VALUE = 1\n",
                                       "core/other.py": "unrelated\n"})
    assert cc.resolve(_control()) == (cc.MOVED, ["core/new/home.py"])


def test_an_anchor_that_vanished_is_retired(tmp_path, monkeypatch):
    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "pass\n", "api/x.py": "pass\n"})
    assert cc.resolve(_control()) == (cc.RETIRED, [])


def test_an_anchor_in_several_files_is_ambiguous(tmp_path, monkeypatch):
    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "pass\n",
                                       "core/a.py": "VALUE = 1\n", "api/b.py": "VALUE = 1\n"})
    status, paths = cc.resolve(_control())
    assert status == cc.AMBIGUOUS and paths == ["api/b.py", "core/a.py"]


def test_an_anchor_twice_in_one_other_file_is_ambiguous(tmp_path, monkeypatch):
    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "pass\n",
                                       "core/a.py": "VALUE = 1\nVALUE = 1\n"})
    assert cc.resolve(_control())[0] == cc.AMBIGUOUS


def test_only_the_governed_tree_is_searched(tmp_path, monkeypatch):
    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "pass\n",
                                       "docs/notes.py": "VALUE = 1\n",
                                       "core/node_modules/x.py": "VALUE = 1\n"})
    assert cc.resolve(_control())[0] == cc.RETIRED


def test_a_moved_control_runs_against_its_new_file_but_does_not_count_as_firing(
        tmp_path, monkeypatch, capsys):
    cc = _tree(tmp_path, monkeypatch, {
        "core/old.py": "pass\n", "core/new.py": "VALUE = 1\n",
        "test_it.py": "import core.new as m\n\ndef test_it():\n    assert m.VALUE == 1\n"})
    monkeypatch.setattr(cc, "CONTROLS", [
        Control(describes="moved guard", path="core/old.py", old="VALUE = 1",
                new="VALUE = 2", tests=["test_it.py::test_it"])])
    monkeypatch.setattr(cc, "run", lambda control: (cc.FIRES, "1 failed"))

    assert cc.main([]) == 1
    printed = capsys.readouterr().out
    assert "MOVED" in printed and "core/new.py" in printed
    assert "fires " not in printed
    assert (tmp_path / "core/new.py").read_text() == "VALUE = 1\n"


def test_retired_and_ambiguous_controls_are_not_run_and_fail_the_run(
        tmp_path, monkeypatch, capsys):
    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "pass\n"})
    monkeypatch.setattr(cc, "CONTROLS", [_control(describes="gone")])
    ran = []
    monkeypatch.setattr(cc, "run", lambda control: ran.append(control) or (cc.FIRES, ""))

    assert cc.main([]) == 1
    printed = capsys.readouterr().out
    assert "RETIRED" in printed and "gone" in printed
    assert not ran
    assert "fires " not in printed


def test_report_moves_prints_and_runs_nothing(tmp_path, monkeypatch, capsys):
    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "pass\n", "core/new.py": "VALUE = 1\n"})
    monkeypatch.setattr(cc, "CONTROLS", [_control()])
    monkeypatch.setattr(cc, "run", lambda control: pytest.fail("must not run"))

    assert cc.main(["--report-moves"]) == 1
    assert "core/old.py -> core/new.py" in capsys.readouterr().out


def test_rewrite_paths_changes_only_the_path_of_moved_controls():
    from elysium.scripts.check_controls import rewrite_paths

    source = (
        "CONTROLS = [\n"
        "    Control(\n"
        "        describes='one',\n"
        "        path='core/a.py',\n"
        "        old='x = \"core/a.py\"',\n"
        "        new='y',\n"
        "        tests=[],\n"
        "    ),\n"
        "    Control(\n"
        "        describes=\"two\",\n"
        "        path=\"core/a.py\",\n"
        "        old='x',\n"
        "        new='y',\n"
        "        tests=[],\n"
        "    ),\n"
        "]\n")
    rewritten, count = rewrite_paths(source, {"one": "src/b.py"})
    assert count == 1
    assert rewritten == source.replace("path='core/a.py'", "path='src/b.py'")


def test_rewrite_paths_option_updates_the_file_it_lives_in(tmp_path, monkeypatch):
    # End to end on a copy of the script, so the real record is untouched.
    import shutil

    cc = _tree(tmp_path, monkeypatch, {"core/old.py": "pass\n", "core/new.py": "VALUE = 1\n"})
    copy = tmp_path / "check_controls_copy.py"
    shutil.copy(cc.__file__, copy)
    text = copy.read_text()
    marker = "CONTROLS = ["
    copy.write_text(text.replace(marker, marker + """
    Control(describes='moved one', path='core/old.py', old='VALUE = 1',
            new='VALUE = 2', tests=['a::b']),
""", 1))
    import importlib.util

    spec = importlib.util.spec_from_file_location("cc_copy", copy)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "SEARCH_ROOTS", ("core", "api"))
    monkeypatch.setattr(module, "CONTROLS", [c for c in module.CONTROLS
                                             if c.describes == "moved one"])

    assert module.main(["--rewrite-paths"]) == 0
    assert "path='core/new.py'" in copy.read_text()
    assert "path='core/old.py'" not in copy.read_text()
