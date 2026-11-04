#!/usr/bin/env bash
# card_worktree.sh ID -- give a worker its own worktree and branch.
#
# Creates ../elysium-wt/<ID> on a new branch card/<ID> from `dev`, and,
# when tools/card_packet.py exists, writes the worker's packet to
# ../elysium-wt/<ID>/.heavy/packet.md and prints that path.
#
# Exit: 0 done; 2 usage or bad id; 3 the branch or directory exists.
set -euo pipefail

if [ "$#" -ne 1 ]; then
    echo "usage: tools/card_worktree.sh ID" >&2
    exit 2
fi
id=$1
case "$id" in
    '' | -* | *[!A-Za-z0-9._-]* | *..*)
        echo "card_worktree: bad card id: $id" >&2
        exit 2
        ;;
esac

root=$(cd "$(dirname "$0")/.." && pwd)
parent=$root/../elysium-wt
dir=$parent/$id
branch=card/$id

if git -C "$root" show-ref --verify --quiet "refs/heads/$branch"; then
    echo "card_worktree: branch $branch already exists" >&2
    exit 3
fi
if [ -e "$dir" ]; then
    echo "card_worktree: $dir already exists" >&2
    exit 3
fi

mkdir -p "$parent"
git -C "$root" worktree add -b "$branch" "$dir" dev >&2
dir=$(cd "$dir" && pwd)

if [ -f "$root/tools/card_packet.py" ]; then
    mkdir -p "$dir/.heavy"
    (cd "$root" && python tools/card_packet.py "$id") > "$dir/.heavy/packet.md"
    echo "$dir/.heavy/packet.md"
else
    echo "card_worktree: tools/card_packet.py does not exist yet; no packet written" >&2
    echo "$dir"
fi
