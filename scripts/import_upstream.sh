#!/usr/bin/env bash
# Imports God's Eye View into screen/, UNTOUCHED, as one commit on the
# astrolabe branch, and proves it is untouched.
#
#   scripts/import_upstream.sh            # the pinned commit below
#   scripts/import_upstream.sh <commit>   # a deliberate upgrade (ROADMAP R6)
#
# WHY ONE UNTOUCHED COMMIT. Every change we make to their screen is then
# a plain diff against their original, which is what FORK.md lists and
# what the MIT notice (screen/LICENSE) travels with. It also keeps patches
# small: their ~2,200 files arrive by this script on each machine, never
# inside a patch.
#
# PROOF, NOT TRUST, AND AFTER THE COMMIT. The commit made must store, at
# screen/, exactly the tree of the upstream commit, and have exactly the
# branch's previous tip as its parent (none on an unborn branch). Hooks
# are not run for this commit, since one that "tidies" files would change
# it; the proof would still catch it. Anything else is undone.
#
# ONLY THE FILES ARRIVE, NOT THEIR HISTORY. The upstream commit is fetched
# into a temporary repository, and only its tree and files are copied into
# yours, so your clone does not become shallow and gains no upstream
# history.
#
# ENVIRONMENT: UPSTREAM (default the GitHub repository), BRANCH (default
# astrolabe), PREFIX (default screen).
set -euo pipefail

fail() { echo "import_upstream: $*" >&2; exit 1; }

PINNED=8978801dfd2a88368074883a87bcd05ffb57ef92   # 31 October 2026, PR #1491
commit="${1:-$PINNED}"
UPSTREAM="${UPSTREAM:-https://github.com/bilawalsidhu/gods-eye-view}"
BRANCH="${BRANCH:-astrolabe}"
PREFIX="${PREFIX:-screen}"

[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || fail "give the full 40-character commit, not '$commit'"
top="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "run this inside the repository"
cd "$top"
[[ "$(git symbolic-ref --short HEAD 2>/dev/null)" == "$BRANCH" ]] || fail "not on $BRANCH"
for state in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
  ! git rev-parse -q --verify "$state" >/dev/null || fail "a merge, cherry-pick or revert is in progress; finish or abort it first"
done
for leftover in rebase-apply rebase-merge; do
  [[ ! -d "$(git rev-parse --git-path "$leftover")" ]] || fail "a rebase or apply is in progress; finish or abort it first"
done
[[ "$(git config --bool core.sparseCheckout || echo false)" != true ]] || fail "sparse checkout is on; the files would not appear on disk. Turn it off first"
git diff --quiet && git diff --cached --quiet || fail "tracked files have uncommitted changes"
[[ ! -e "$PREFIX" && ! -L "$PREFIX" ]] || fail "$PREFIX already exists; an upgrade replaces it deliberately (ROADMAP R6), not with this script as it stands"

before="$(git rev-parse -q --verify HEAD || true)"   # empty on an unborn branch
scratch="$(mktemp -d)"
imported=no
undo() {
  if [[ "$imported" == yes ]]; then
    if [[ -n "$before" ]]; then git reset -q --hard "$before"; else git update-ref -d HEAD 2>/dev/null || true; git read-tree --empty; fi
    rm -rf -- "$PREFIX"
  fi
}
cleanup() { rm -rf -- "$scratch"; }
trap 'undo; cleanup; echo "import_upstream: stopped part way; nothing was imported and your branch is as it was. Read the message above, fix it, and run this again" >&2; exit 1' ERR INT TERM
trap cleanup EXIT

echo "Fetching $commit from $UPSTREAM ..."
git init -q --bare "$scratch"
git -C "$scratch" fetch -q --depth 1 "$UPSTREAM" "$commit" || fail "could not fetch $commit"
[[ "$(git -C "$scratch" cat-file -t "$commit" 2>/dev/null)" == commit ]] || fail "$commit is not a commit"
tree="$(git -C "$scratch" rev-parse "$commit^{tree}")"
git -C "$scratch" rev-list --objects "$tree" | cut -d' ' -f1 \
  | git -C "$scratch" pack-objects -q --stdout | git index-pack --stdin >/dev/null
[[ "$(git cat-file -t "$tree")" == tree ]] || fail "the files did not arrive"

imported=yes
git read-tree --prefix="$PREFIX/" -u "$tree"
git -c core.hooksPath=/dev/null commit -q --no-verify -m "Import God's Eye View ${commit:0:12} into $PREFIX/, untouched

From $UPSTREAM at $commit
(tree $tree). MIT licensed: see $PREFIX/LICENSE. Nothing in $PREFIX/
is changed by this commit; every later change is listed in FORK.md.
Third-party data and assets keep their own terms ($PREFIX/DATA_SOURCES.md)."

stored="$(git rev-parse "HEAD:$PREFIX")"
parents="$(git rev-list --parents -n 1 HEAD | cut -s -d' ' -f2-)"
if [[ "$stored" != "$tree" || "$parents" != "$before" ]]; then
  undo
  fail "the commit is not upstream's files on top of $BRANCH (stored $stored, expected $tree; parents '$parents', expected '$before'); it has been undone"
fi
imported=done
echo "IMPORTED: $PREFIX/ is upstream $commit, tree $tree, untouched."
