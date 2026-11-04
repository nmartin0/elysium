"""diffsize counts the lines a person reads and refuses an unexplained giant."""

import subprocess

import diffsize
import pytest


def numstat(*entries):
    return "".join(f"{a}\t{d}\t{path}\0" for a, d, path in entries)


def test_added_and_deleted_lines_are_summed():
    size = diffsize.parse_numstat(numstat((10, 2, "src/a.py"), (5, 0, "tests/b.py")))

    assert (size.added, size.deleted, size.total) == (15, 2, 17)


@pytest.mark.parametrize("path", [
    "uv.lock", "ui/package-lock.json", "src/elysium/api/v2/openapi.json",
    "ui/packages/shell-api/src/generated/schema.d.ts", "docs/reference/cli.md",
    "controls/legacy/x.toml", "quality/ruff-ignores.txt",
])
def test_generated_paths_are_left_out(path):
    assert diffsize.parse_numstat(numstat((500, 500, path))).total == 0


def test_a_binary_file_counts_nothing():
    assert diffsize.parse_numstat("-\t-\tlogo.png\0").total == 0


def test_a_rename_is_read_by_its_new_path():
    output = "3\t1\t\0old/name.py\0new/name.py\0" + numstat((4, 0, "src/c.py"))

    assert diffsize.parse_numstat(output).total == 8


def test_over_the_limit_needs_a_large_change_line():
    big = diffsize.Size(900, 200)

    assert diffsize.too_big(big, "Do a lot\n\nCard: T0.1\n")
    assert not diffsize.too_big(big, "Do a lot\n\nLarge-change: mechanical conversion\n")
    assert not diffsize.too_big(diffsize.Size(1000, 0), "Do a lot\n")


def test_an_empty_large_change_line_does_not_count():
    assert diffsize.too_big(diffsize.Size(2000, 0), "x\n\nLarge-change:\n")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com",  # noqa: S603, S607
                        *args], check=True, capture_output=True)

    git("init", "-q", "-b", "dev")
    (tmp_path / "base.txt").write_text("base\n")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    monkeypatch.setattr(diffsize, "ROOT", tmp_path)

    def commit(lines, message):
        (tmp_path / "big.txt").write_text("x\n" * lines)
        git("add", ".")
        git("commit", "-q", "-m", message)

    return tmp_path, git, commit


def test_a_giant_commit_without_the_line_exits_eight(repo, capsys):
    _, git, commit = repo
    git("checkout", "-q", "-b", "card/x")
    commit(1500, "A giant change")

    assert diffsize.main(["--base", "dev"]) == 8
    assert "TOO BIG" in capsys.readouterr().out


def test_a_giant_commit_with_the_line_passes(repo, capsys):
    _, git, commit = repo
    git("checkout", "-q", "-b", "card/x")
    commit(1500, "A giant change\n\nLarge-change: a mechanical conversion")

    assert diffsize.main(["--base", "dev"]) == 0
    assert "Large-change given" in capsys.readouterr().out


def test_the_default_base_is_where_the_branch_left_dev(repo, capsys):
    _, git, commit = repo
    git("checkout", "-q", "-b", "card/x")
    commit(10, "A small change")

    assert diffsize.main([]) == 0
    assert "A small change" in capsys.readouterr().out


def test_the_staged_change_is_measured_for_the_commit_msg_hook(repo, tmp_path_factory):
    root, git, _ = repo
    (root / "big.txt").write_text("x\n" * 1200)
    git("add", ".")
    message = tmp_path_factory.mktemp("msg") / "MSG"
    message.write_text("A giant change\n\nCard: T0.1\n")

    assert diffsize.main(["--commit-msg", str(message)]) == 8

    message.write_text("A giant change\n\nLarge-change: because\n")

    assert diffsize.main(["--commit-msg", str(message)]) == 0


def test_comment_lines_of_the_editor_template_are_ignored(repo, tmp_path_factory):
    root, git, _ = repo
    (root / "big.txt").write_text("x\n" * 1200)
    git("add", ".")
    message = tmp_path_factory.mktemp("msg") / "MSG"
    message.write_text("A change\n\n# Large-change: this is a template comment\n")

    assert diffsize.main(["--commit-msg", str(message)]) == 8
