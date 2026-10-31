#!/usr/bin/env bash
# Applies a patch from Claude to your clone, pushes it, and says whether
# the push really landed.
#
#   scripts/apply_patch.sh ~/Downloads/<name>.patch
#
# WHY A SCRIPT. On 28 October four rounds were lost because an earlier,
# interrupted `git am` had left .git/rebase-apply behind: every later
# `git am` printed "previous rebase directory still exists" in the middle
# of a pasted block and the push after it reported "Everything
# up-to-date", which reads as success. This checks for that FIRST, stops at
# the first failure, and proves the result at the end.
#
# ENVIRONMENT: BRANCH (default dev), REMOTE (default origin).
set -euo pipefail

fail() { echo "apply_patch: $*" >&2; exit 1; }

patch="${1:-}"
[[ -n "$patch" ]] || fail "usage: scripts/apply_patch.sh <patch-file>"
[[ -s "$patch" ]] || fail "$patch is missing or empty -- download it again"
BRANCH="${BRANCH:-dev}"; REMOTE="${REMOTE:-origin}"
patch="$(cd "$(dirname "$patch")" && pwd)/$(basename "$patch")"
cd "$(git rev-parse --show-toplevel)"

for leftover in rebase-apply rebase-merge; do
  if [[ -d "$(git rev-parse --git-path "$leftover")" ]]; then
    fail "an earlier apply or rebase was interrupted and left .git/$leftover behind. Run: git am --abort   (or, if that says nothing is in progress: rm -rf .git/$leftover) and then run this again"
  fi
done
git diff --quiet && git diff --cached --quiet \
  || fail "tracked files have uncommitted changes. Commit or stash them first"

[[ "$(git rev-parse --abbrev-ref HEAD)" == "$BRANCH" ]] || fail "you are not on $BRANCH. Run: git checkout $BRANCH"
git pull -q --ff-only "$REMOTE" "$BRANCH" || fail "could not fast-forward $BRANCH from $REMOTE"
[[ "$(git rev-list --count "$REMOTE/$BRANCH"..HEAD)" == 0 ]] \
  || fail "$BRANCH has commits $REMOTE/$BRANCH lacks; pushing would publish them too. Look at: git log $REMOTE/$BRANCH..HEAD"
expected="$(grep -c '^From [0-9a-f]\{40\} ' "$patch" || true)"
before="$(git rev-parse HEAD)"

if ! git am -q "$patch"; then
  echo "apply_patch: git am stopped. Nothing was pushed. To go back: git am --abort" >&2
  exit 1
fi
applied="$(git rev-list --count "$before"..HEAD)"
[[ "$applied" == "$expected" ]] || fail "the patch holds $expected commit(s) but $applied were applied"

git push -q "$REMOTE" "$BRANCH" || fail "the push was refused. The commits are applied locally; read the message above"
git fetch -q "$REMOTE"
behind_ahead="$(git rev-list --left-right --count "$REMOTE/$BRANCH"...HEAD)"
[[ "$behind_ahead" == $'0\t0' ]] || fail "after the push $REMOTE/$BRANCH and $BRANCH differ (behind/ahead: $behind_ahead)"

git log --oneline -"$applied"
echo "PUSHED: $applied commit(s); $BRANCH matches $REMOTE/$BRANCH."
echo "Now: restart uvicorn if api/ or core/ changed; run 'cd ui && npm run build' if ui/ changed."
