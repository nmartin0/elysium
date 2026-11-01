#!/usr/bin/env bash
# Makes the patch for the commits on dev that origin/dev lacks, and refuses
# to hand over one that would not apply or is not what was committed.
#
#   scripts/make_patch.sh <name> [expected-commits]
#
# WHY A SCRIPT. These checks used to be paragraphs in CLAUDE.md, and a
# paragraph is a guideline the one following it may skip. Skipped, they
# cost real time: a patch of the wrong size, an old patch left in the
# outputs folder. A rule with no exceptions belongs
# in something that enforces it (PRINCIPLES.md section 13).
#
# CHECKS, each refusing with what to do: a clean tracked tree; at least one
# commit ahead of the base, and exactly `expected-commits` when given; the
# patch holds as many commits as were counted; and it APPLIES to a fresh
# copy of the base. (Commits carry no attribution lines: owner's decision,
# 31 October.)
#
# ENVIRONMENT: OUT (default /mnt/user-data/outputs), BASE (default
# origin/dev), BRANCH (default dev), NO_FETCH=1 to skip the fetch.
set -euo pipefail

fail() { echo "make_patch: $*" >&2; exit 1; }

name="${1:-}"; expected="${2:-}"
[[ -n "$name" ]] || fail "usage: scripts/make_patch.sh <name> [expected-commits]"
OUT="${OUT:-/mnt/user-data/outputs}"; BASE="${BASE:-origin/dev}"; BRANCH="${BRANCH:-dev}"
[[ "$OUT" = /* ]] || OUT="$PWD/$OUT"
cd "$(git rev-parse --show-toplevel)"

[[ "$(git rev-parse --abbrev-ref HEAD)" == "$BRANCH" ]] || fail "not on $BRANCH"
git diff --quiet && git diff --cached --quiet \
  || fail "tracked files have uncommitted changes -- commit them or set them aside"
[[ -n "${NO_FETCH:-}" ]] || git fetch -q "${BASE%%/*}"

[[ -z "$(git rev-list --merges "$BASE"..HEAD)" ]] \
  || fail "there is a merge commit ahead of $BASE; format-patch drops merges. Rebase to a straight line: git rebase $BASE"
ahead="$(git rev-list --count "$BASE"..HEAD)"
[[ "$ahead" -gt 0 ]] || fail "nothing is ahead of $BASE, so there is nothing to send"
if [[ -n "$expected" && "$ahead" != "$expected" ]]; then
  fail "expected $expected commit(s) but $ahead are ahead of $BASE. Either one was applied already under a different hash (rebase: git rebase --onto $BASE <that commit>), or the base moved (git fetch && git rebase $BASE)"
fi

mkdir -p "$OUT"
rm -f "$OUT"/*.patch
patch="$OUT/$name.patch"
git format-patch "$BASE"..HEAD --stdout > "$patch"
made="$(grep -c '^From [0-9a-f]\{40\} ' "$patch" || true)"
[[ "$made" == "$ahead" ]] || { rm -f "$patch"; fail "the patch holds $made commit(s) but $ahead were counted"; }

probe="vfy-$$"
cleanup() { git checkout -q "$BRANCH"; git branch -D -q "$probe" 2>/dev/null || true; }
trap cleanup EXIT
git checkout -q -B "$probe" "$BASE"
if ! git am -q "$patch"; then
  git am --abort 2>/dev/null || true
  rm -f "$patch"
  fail "the patch does not apply to $BASE; it has been removed. Rebase onto $BASE and make it again"
fi
git diff --quiet "$probe" "$BRANCH" \
  || { rm -f "$patch"; fail "applying the patch to $BASE does not give exactly the files of $BRANCH; rebase onto $BASE and make it again"; }
echo "DRYRUN_OK: $made commit(s), $patch"
