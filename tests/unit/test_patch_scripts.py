"""The two patch scripts refuse what went wrong on 28 October, and work otherwise.

Each test builds a throwaway bare remote and two clones in a temp directory,
so nothing here touches the real repository or the network.
"""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MAKE = REPO / "scripts" / "make_patch.sh"
APPLY = REPO / "scripts" / "apply_patch.sh"


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(cwd)},
    ).stdout


def run(script, cwd, *args, **env):
    full = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(cwd), "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", **env}
    return subprocess.run(["bash", str(script), *args], cwd=cwd, capture_output=True, text=True, env=full)


def commit(clone, name):
    (clone / name).write_text(name)
    git(clone, "add", name)
    git(clone, "commit", "-q", "-m", f"add {name}")


@pytest.fixture
def world(tmp_path):
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(bare))
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(bare), str(work))
    git(work, "checkout", "-q", "-b", "dev")
    commit(work, "base.txt")
    git(work, "push", "-q", "origin", "dev")
    out = tmp_path / "out"
    out.mkdir()
    mine = tmp_path / "mine"
    git(tmp_path, "clone", "-q", "-b", "dev", str(bare), str(mine))
    return {"bare": bare, "work": work, "out": out, "mine": mine}


def make(world, *args):
    return run(MAKE, world["work"], *args, OUT=str(world["out"]))


def test_make_patch_happy_path_counts_and_applies(world):
    commit(world["work"], "one.txt")
    commit(world["work"], "two.txt")
    result = make(world, "good", "2")
    assert result.returncode == 0, result.stderr
    assert "DRYRUN_OK: 2 commit(s)" in result.stdout
    assert (world["out"] / "good.patch").read_text().count("\nFrom ") + 1 == 2
    assert git(world["work"], "rev-parse", "--abbrev-ref", "HEAD").strip() == "dev"


def test_make_patch_refuses_wrong_commit_count(world):
    commit(world["work"], "one.txt")
    result = make(world, "bad", "2")
    assert result.returncode != 0
    assert "expected 2 commit(s) but 1" in result.stderr
    assert not list(world["out"].glob("*.patch"))


def test_make_patch_refuses_nothing_to_send(world):
    result = make(world, "none")
    assert result.returncode != 0
    assert "nothing is ahead" in result.stderr



def test_make_patch_refuses_a_dirty_tree(world):
    commit(world["work"], "one.txt")
    (world["work"] / "base.txt").write_text("changed")
    result = make(world, "dirty")
    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr


def test_make_patch_clears_old_patches(world):
    (world["out"] / "stale.patch").write_text("old")
    commit(world["work"], "one.txt")
    assert make(world, "fresh").returncode == 0
    assert [p.name for p in world["out"].glob("*.patch")] == ["fresh.patch"]


def test_make_patch_refuses_a_patch_that_will_not_apply(world):
    commit(world["work"], "one.txt")
    # the remote moves on with a conflicting change to the same file
    other = world["work"].parent / "other"
    git(world["work"].parent, "clone", "-q", "-b", "dev", str(world["bare"]), str(other))
    (other / "one.txt").write_text("conflict")
    git(other, "add", "one.txt")
    git(other, "commit", "-q", "-m", "conflict")
    git(other, "push", "-q", "origin", "dev")
    result = make(world, "clash")
    assert result.returncode != 0
    assert "does not apply" in result.stderr or "ahead" in result.stderr
    assert not list(world["out"].glob("*.patch"))


def patch_for_mine(world):
    commit(world["work"], "one.txt")
    assert make(world, "p").returncode == 0
    return world["out"] / "p.patch"


def apply(world, patch):
    return run(APPLY, world["mine"], str(patch))


def test_apply_patch_applies_pushes_and_proves_it(world):
    patch = patch_for_mine(world)
    result = apply(world, patch)
    assert result.returncode == 0, result.stderr
    assert "PUSHED: 1 commit(s)" in result.stdout
    remote = git(world["mine"], "ls-remote", "origin", "dev").split()[0]
    assert remote == git(world["mine"], "rev-parse", "HEAD").strip()


def test_apply_patch_names_the_leftover_rebase_directory(world):
    patch = patch_for_mine(world)
    (world["mine"] / ".git" / "rebase-apply").mkdir()
    result = apply(world, patch)
    assert result.returncode != 0
    assert "left .git/rebase-apply behind" in result.stderr
    assert git(world["mine"], "rev-list", "--count", "origin/dev..HEAD").strip() == "0"


def test_apply_patch_refuses_a_missing_patch(world):
    result = apply(world, world["out"] / "nope.patch")
    assert result.returncode != 0
    assert "missing or empty" in result.stderr


def test_apply_patch_refuses_a_dirty_tree(world):
    patch = patch_for_mine(world)
    (world["mine"] / "base.txt").write_text("edited")
    result = apply(world, patch)
    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr


def test_apply_patch_does_not_call_a_push_that_did_not_land_a_success(world):
    """A remote that accepts the push and then puts the branch back."""
    patch = patch_for_mine(world)
    old = git(world["mine"], "rev-parse", "HEAD").strip()
    hook = world["bare"] / "hooks" / "post-receive"
    hook.write_text(f"#!/bin/sh\ngit update-ref refs/heads/dev {old}\n")
    hook.chmod(0o755)
    result = apply(world, patch)
    assert result.returncode != 0
    assert "PUSHED" not in result.stdout
    assert "differ" in result.stderr


def test_a_message_line_starting_with_from_does_not_inflate_the_count(world):
    (world["work"] / "f.txt").write_text("f")
    git(world["work"], "add", "f.txt")
    git(world["work"], "commit", "-q", "-m", "subject\n\nFrom the start this was wrong.")
    result = make(world, "from", "1")
    assert result.returncode == 0, result.stderr



def test_make_patch_refuses_a_merge_and_leaves_no_patch(world):
    work = world["work"]
    git(work, "checkout", "-q", "-b", "side")
    commit(work, "s.txt")
    git(work, "checkout", "-q", "dev")
    commit(work, "d.txt")
    git(work, "merge", "-q", "--no-ff", "-m", "merge", "side")
    result = make(world, "m")
    assert result.returncode != 0
    assert "merge commit" in result.stderr
    assert not list(world["out"].glob("*.patch"))


def test_make_patch_accepts_a_relative_output_folder_from_a_subfolder(world):
    commit(world["work"], "one.txt")
    sub = world["work"] / "sub"
    sub.mkdir()
    result = run(MAKE, sub, "rel", OUT="rel")
    assert result.returncode == 0, result.stderr
    assert (sub / "rel" / "rel.patch").exists()


def test_apply_patch_accepts_a_relative_patch_path_from_a_subfolder(world):
    patch = patch_for_mine(world)
    sub = world["mine"] / "sub"
    sub.mkdir()
    (sub / "p.patch").write_text(patch.read_text())
    result = run(APPLY, sub, "p.patch")
    assert result.returncode == 0, result.stderr


def test_apply_patch_refuses_to_publish_unrelated_local_commits(world):
    patch = patch_for_mine(world)
    commit(world["mine"], "private.txt")
    result = apply(world, patch)
    assert result.returncode != 0
    assert "lacks" in result.stderr
    assert git(world["bare"], "log", "--oneline", "dev").count("\n") == 1


def test_apply_patch_refuses_when_not_on_the_branch(world):
    patch = patch_for_mine(world)
    git(world["mine"], "checkout", "-q", "-b", "other")
    result = apply(world, patch)
    assert result.returncode != 0
    assert "not on dev" in result.stderr


def test_make_patch_refuses_when_the_base_moved_without_a_conflict(world):
    """The patch applies cleanly, but to different files than were tested."""
    commit(world["work"], "one.txt")
    other = world["work"].parent / "other"
    git(world["work"].parent, "clone", "-q", "-b", "dev", str(world["bare"]), str(other))
    commit(other, "elsewhere.txt")
    git(other, "push", "-q", "origin", "dev")
    result = make(world, "moved")
    assert result.returncode != 0
    assert "exactly the files" in result.stderr
    assert not list(world["out"].glob("*.patch"))
