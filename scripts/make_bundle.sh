#!/usr/bin/env bash
# Packs the unapplied work of several branches into ONE file, so the owner
# can let work pile up and apply and push it all in one go.
#
#   scripts/make_bundle.sh <name> <lane>=<repo-dir>:<base> [<lane>=<repo-dir>:<base> ...]
#
#   e.g. scripts/make_bundle.sh bundle-2026-11-01a \
#          dev=/home/claude/elysium:origin/dev \
#          astrolabe=/home/claude/elysium-globe:origin/astrolabe
#
# A LANE is a branch checked out in its own directory (Elysium's dev and
# each sub-app's branch). The base is what the owner already has: everything
# after it goes in. The work of a lane that has nothing new is left out.
# Lanes are applied in the order given, so a sub-app change that needs an
# Elysium change comes after it.
#
# EACH LANE'S PATCH is made and dry-run by make_patch.sh (clean tree, count,
# applies to the base), so a bundle is no less checked than a single patch.
# The result is OUT/<name>.tar holding <name>/ORDER and one patch per lane;
# scripts/apply_bundle.sh applies it.
#
# ENVIRONMENT: OUT (default /mnt/user-data/outputs), NO_FETCH=1 to skip the
# fetch each lane does.
set -euo pipefail

fail() { echo "make_bundle: $*" >&2; exit 1; }

name="${1:-}"; shift || true
[[ -n "$name" && $# -ge 1 ]] || fail "usage: scripts/make_bundle.sh <name> <lane>=<repo-dir>:<base> ..."
OUT="${OUT:-/mnt/user-data/outputs}"
[[ "$OUT" = /* ]] || OUT="$PWD/$OUT"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
mkdir -p "$work/$name" "$OUT"
: > "$work/$name/ORDER"

for spec in "$@"; do
  lane="${spec%%=*}"; rest="${spec#*=}"; dir="${rest%:*}"; base="${rest##*:}"
  [[ "$spec" == *=*:* && -n "$lane" && -d "$dir" ]] || fail "bad lane '$spec' (want lane=/dir:base, and the directory must exist)"
  [[ "$lane" =~ ^[A-Za-z0-9_-]+$ ]] || fail "lane name '$lane' may hold only letters, digits, - and _"
  ahead="$(git -C "$dir" rev-list --count "$base"..HEAD 2>/dev/null)" \
    || fail "$lane: cannot count commits after $base in $dir"
  if [[ "$ahead" == 0 ]]; then echo "make_bundle: $lane has nothing new; left out"; continue; fi
  n=$(( $(wc -l < "$work/$name/ORDER") + 1 ))
  file="$(printf '%02d' "$n")-$lane"
  mkdir -p "$work/$name/$lane"
  # A base that is a bare commit (a sub-app not yet pushed) has no remote to fetch.
  nofetch="${NO_FETCH:-}"; [[ "$base" == */* ]] || nofetch=1
  ( cd "$dir" && NO_FETCH="$nofetch" BASE="$base" BRANCH="$lane" OUT="$work/$name/$lane" "$here/make_patch.sh" "$file" "$ahead" ) >/dev/null \
    || fail "$lane: make_patch refused; run it in $dir to see why"
  printf '%s\t%s/%s.patch\t%s\n' "$lane" "$lane" "$file" "$ahead" >> "$work/$name/ORDER"
done

[[ -s "$work/$name/ORDER" ]] || fail "nothing new in any lane"
tar -C "$work" -cf "$OUT/$name.tar" "$name"
echo "BUNDLE_OK: $OUT/$name.tar"
cat "$work/$name/ORDER"
