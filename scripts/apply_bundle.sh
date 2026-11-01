#!/usr/bin/env bash
# Applies a bundle from Claude: each lane's patch, in order, to that lane's
# own clone, pushing each and proving it landed (scripts/apply_patch.sh does
# the work for each lane).
#
#   scripts/apply_bundle.sh ~/Downloads/<name>.tar
#
# Run it from your Elysium clone (the dev lane). The other lanes live in
# sibling directories, one per sub-app: ../elysium-<lane>, a git worktree
# of the same repository on branch <lane>. Set LANE_DIR_<lane>=/path to put
# one elsewhere. If a lane's directory is missing the script stops BEFORE
# applying anything and says how to make it.
#
# Nothing is applied unless every lane's directory is there and clean, so a
# bundle is not left half-applied for a reason that was knowable up front.
set -euo pipefail

fail() { echo "apply_bundle: $*" >&2; exit 1; }

bundle="${1:-}"
[[ -s "$bundle" ]] || fail "usage: scripts/apply_bundle.sh <bundle.tar> (missing or empty: '$bundle')"
bundle="$(cd "$(dirname "$bundle")" && pwd)/$(basename "$bundle")"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(git -C "$here" rev-parse --show-toplevel)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
tar -C "$work" -xf "$bundle"
dir="$(ls "$work")"; [[ -f "$work/$dir/ORDER" ]] || fail "$bundle has no ORDER file; it is not a bundle"

lane_dir() {
  local var="LANE_DIR_${1//-/_}"
  if [[ -n "${!var:-}" ]]; then echo "${!var}"
  elif [[ "$1" == dev ]]; then echo "$root"
  else echo "$(dirname "$root")/elysium-$1"; fi
}

while IFS=$'\t' read -r lane patch count; do
  d="$(lane_dir "$lane")"
  [[ -d "$d" ]] || fail "lane '$lane' has no directory at $d. Make it once with: git -C '$root' worktree add '$d' $lane   (the branch must exist; see docs/bundles.md). Nothing was applied"
  [[ "$(git -C "$d" rev-parse --abbrev-ref HEAD)" == "$lane" ]] || fail "$d is not on branch $lane. Nothing was applied"
  git -C "$d" diff --quiet && git -C "$d" diff --cached --quiet || fail "$d has uncommitted changes. Nothing was applied"
done < "$work/$dir/ORDER"

while IFS=$'\t' read -r lane patch count; do
  d="$(lane_dir "$lane")"
  echo "== $lane ($count commit(s)) in $d"
  ( cd "$d" && BRANCH="$lane" "$here/apply_patch.sh" "$work/$dir/$patch" )
done < "$work/$dir/ORDER"
echo "BUNDLE_APPLIED: every lane pushed and proved."
