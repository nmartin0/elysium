#!/usr/bin/env bash
# integrate_card.sh ID -- the integrator merges one reviewed card.
#
# Run in the main worktree, on `dev`. Rebases card/<ID> onto dev, then
# fast-forwards dev, then runs the fast check and exits with its status.
# A conflict in a regenerated file is resolved by regenerating it with its
# tool; a conflict anywhere else (or in a file whose tool does not exist)
# aborts the rebase, prints the paths and exits 6.
#
# The rebase runs inside the card's worktree when the branch is checked
# out there (git refuses to check a branch out twice), which is the same
# operation as `git rebase dev card/<ID>`.
#
# Exit: 0 merged and checked; 2 usage or wrong branch; 6 conflict;
# otherwise the status of the failing git command or of the check.
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: tools/integrate_card.sh ID" >&2
    exit 2
fi
id=$1
case "$id" in
    '' | -* | *[!A-Za-z0-9._-]* | *..*)
        echo "integrate_card: bad card id: $id" >&2
        exit 2
        ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
cd "$root"
branch=card/$id

if [ "$(git symbolic-ref --short -q HEAD || true)" != "dev" ]; then
    echo "integrate_card: run this in the main worktree on dev" >&2
    exit 2
fi
if ! git show-ref --verify --quiet "refs/heads/$branch"; then
    echo "integrate_card: no branch $branch" >&2
    exit 2
fi

# The worktree where the card branch is checked out, if any.
wt=$(git worktree list --porcelain | awk -v b="refs/heads/$branch" '
    $1 == "worktree" { path = substr($0, 10) }
    $1 == "branch" && $2 == b { print path }')

rb() { # run a git command where the rebase is happening
    if [ -n "$wt" ]; then git -C "$wt" "$@"; else git "$@"; fi
}

# regen FILE: print the command that regenerates FILE, or nothing when
# its tool does not exist yet.
regen() {
    cd "${wt:-$root}"
    case "$1" in
        src/elysium/api/v2/openapi.json)
            [ -f src/elysium/api/v2/openapi.py ] &&
                echo "python -m elysium.api.v2.openapi --write" || true ;;
        ui/packages/shell-api/src/generated/schema.d.ts)
            [ -f ui/package.json ] && grep -q '"gen:client"' ui/package.json &&
                echo "npm run gen:client --prefix ui" || true ;;
        docs/reference/*)
            [ -f tools/gen_docs.py ] &&
                echo "python tools/gen_docs.py --write" || true ;;
        uv.lock)
            command -v uv > /dev/null 2>&1 && [ -f pyproject.toml ] &&
                echo "uv lock" || true ;;
        quality/ruff-ignores.txt)
            [ -f tools/ruff_baseline.py ] &&
                echo "python tools/ruff_baseline.py --write" || true ;;
        quality/comment-lint-baseline.txt)
            [ -f tools/lint_comments.py ] &&
                echo "python tools/lint_comments.py --write-baseline" || true ;;
    esac
}

is_generated() {
    case "$1" in
        src/elysium/api/v2/openapi.json | \
        ui/packages/shell-api/src/generated/schema.d.ts | \
        docs/reference/* | uv.lock | \
        quality/ruff-ignores.txt | quality/comment-lint-baseline.txt) return 0 ;;
    esac
    return 1
}

give_up() { # give_up PATHS...
    echo "integrate_card: cannot resolve the conflict in:" >&2
    printf '  %s\n' "$@" >&2
    rb rebase --abort
    exit 6
}

if ! rb rebase dev $([ -n "$wt" ] || echo "$branch"); then
    while [ -d "$(rb rev-parse --git-path rebase-merge)" ] ||
          [ -d "$(rb rev-parse --git-path rebase-apply)" ]; do
        mapfile -t conflicted < <(rb diff --name-only --diff-filter=U)
        if [ "${#conflicted[@]}" -eq 0 ]; then
            # Stopped without a conflicted path: not ours to fix.
            give_up "(rebase stopped with no conflicted paths)"
        fi
        for f in "${conflicted[@]}"; do
            is_generated "$f" || give_up "${conflicted[@]}"
            [ -n "$(regen "$f")" ] || give_up "$f (no tool to regenerate it yet)"
        done
        top=${wt:-$root}
        for f in "${conflicted[@]}"; do
            cmd=$(regen "$f")
            # Clear the markers (keep dev's side), regenerate from the
            # merged tree, stage the result.
            rb checkout --ours -- "$f" || give_up "$f"
            (cd "$top" && bash -c "$cmd") > /dev/null ||
                give_up "$f (regeneration failed: $cmd)"
            rb add -- "$f"
        done
        if rb diff --name-only --diff-filter=U | grep -q .; then
            give_up "$(rb diff --name-only --diff-filter=U)"
        fi
        # A further conflict in the next commit sends the loop round again.
        GIT_EDITOR=true rb rebase --continue > /dev/null 2>&1 || true
    done
fi

git checkout dev
git merge --ff-only "$branch"

if [ -x ./check.sh ]; then
    exec ./check.sh --fast
fi
./lint.sh
exec python -m pytest tests/unit -q -x
