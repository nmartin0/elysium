"""Comments carry rules, not history (N40)."""

from collections import Counter

import lint_comments as lc
import pytest


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "ROOT", tmp_path)
    monkeypatch.setattr(lc, "BASELINE", tmp_path / "quality" / "baseline.txt")
    (tmp_path / "src").mkdir()

    def write(name, text):
        (tmp_path / "src" / name).write_text(text)

    return write


@pytest.mark.parametrize("comment", [
    "# see GOLD-9",
    "# the NEW-12 rewrite",
    "# decided 3 November 2026",
    "# since 2026-10-19",
    "# see ROADMAP for why",
    "# step 5h of the plan",
    "# the owner asked for this",
    "# as I said earlier",
    "# in this session",
    "# the reviewer said so",
])
def test_history_in_a_comment_is_flagged(tree, comment):
    tree("a.py", f"x = 1  {comment}\n")

    assert lc.main(["--check"]) == 1


@pytest.mark.parametrize("comment", [
    "# a rule: names, never contents",
    "# UTF-8 and SHA-256 are fine",
    "# step by step, one at a time",
])
def test_a_rule_is_not_flagged(tree, comment):
    tree("a.py", f"x = 1  {comment}\n")

    assert lc.main(["--check"]) == 0


def test_history_in_a_docstring_is_flagged_with_its_line(tree, capsys):
    tree("a.py", '"""A module.\n\nIt was added for BLK-4.\n"""\n')

    assert lc.main(["--check"]) == 1
    assert "src/a.py:3: ticket code" in capsys.readouterr().out


def test_history_in_a_string_that_is_not_a_docstring_is_not_flagged(tree):
    tree("a.py", 'MESSAGE = "see GOLD-9"\n')

    assert lc.main(["--check"]) == 0


def test_a_hit_in_the_baseline_passes_and_a_second_copy_fails(tree):
    tree("a.py", "# see GOLD-9\nx = 1\n")
    assert lc.main(["--write-baseline"]) == 0
    assert lc.main(["--check"]) == 0

    tree("a.py", "# see GOLD-9\nx = 1\n# see GOLD-9\n")
    assert lc.main(["--check"]) == 1


def test_a_baselined_line_still_passes_when_it_moves(tree):
    tree("a.py", "# see GOLD-9\nx = 1\n")
    lc.main(["--write-baseline"])

    tree("a.py", "y = 2\nz = 3\n# see GOLD-9\nx = 1\n")

    assert lc.main(["--check"]) == 0


def test_a_changed_line_is_a_new_hit(tree):
    tree("a.py", "# see GOLD-9\n")
    lc.main(["--write-baseline"])

    tree("a.py", "# see GOLD-10\n")

    assert lc.main(["--check"]) == 1


def test_only_src_is_read(tree, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.py").write_text("# see GOLD-9\n")
    tree("a.py", "x = 1\n")

    assert lc.main(["--check"]) == 0


def test_new_hits_counts_duplicates():
    hits = [lc.Hit("a.py", 1, "# x", "date"), lc.Hit("a.py", 2, "# x", "date")]

    assert len(lc.new_hits(hits, Counter({hits[0].key: 1}))) == 1


def test_the_repository_has_no_hit_outside_its_baseline():
    assert lc.main(["--check"]) == 0
