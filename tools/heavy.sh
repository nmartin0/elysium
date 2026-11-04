#!/usr/bin/env bash
# heavy.sh NAME CMD... -- run one long command the one allowed way.
#
# The command runs under `nice -n 10` and `timeout` (HEAVY_TIMEOUT
# seconds, default 1800). All of its output goes to
# .heavy/<utc>-<NAME>.log and its exit status to .heavy/<utc>-<NAME>.exit;
# the last 60 lines and the status are printed, and the status is this
# script's own. A run named `full` first takes an exclusive lock in the
# repository's common git directory, so full suites started from several
# worktrees queue instead of running together. The wait is not part of
# the timeout.
#
# Exit: the command's status (124 when the timeout stopped it); 2 usage.
set -euo pipefail

if [ "$#" -lt 2 ]; then
    echo "usage: tools/heavy.sh NAME CMD..." >&2
    exit 2
fi
name=$1
shift
case "$name" in
    '' | -* | *[!A-Za-z0-9._-]*)
        echo "heavy: bad run name: $name" >&2
        exit 2
        ;;
esac

root=$(git rev-parse --show-toplevel)
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$root/.heavy"
log=$root/.heavy/$stamp-$name.log
exitfile=$root/.heavy/$stamp-$name.exit
limit=${HEAVY_TIMEOUT:-1800}

runner=(nice -n 10 timeout "$limit" "$@")
if [ "$name" = full ]; then
    lock=$(git rev-parse --git-common-dir)/heavy-full.lock
    runner=(flock "$lock" "${runner[@]}")
fi

status=0
(cd "$root" && "${runner[@]}") > "$log" 2>&1 || status=$?
echo "$status" > "$exitfile"

tail -n 60 "$log"
echo "heavy: $name exit $status (log: $log)"
exit "$status"
