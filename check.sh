#!/usr/bin/env bash
# check.sh [--fast|--full] [-k EXPR] -- every gate, in one place.
#
# Runs every step even after a failure, prints `step | exit | seconds`
# and exits non-zero when any step failed. A step that is not applicable
# in the chosen mode, or whose tool does not exist yet, is listed as
# "skipped" and counts as passed.
#
#   --fast   (default) ruff, mypy, vulture, import-linter, lock check,
#            comment lint, diffsize (report only), the unit tests (or,
#            with -k, the tests matching EXPR), the controls' anchors
#            and the UI lint.
#   --full   the same with every test, every control fired, and vitest before the UI lint.
#   -k EXPR  pytest's -k expression for the test step.
#
# Environment: CHECK_SH_STEPS_FILE names a file of `name<TAB>command`
# lines that replaces the built-in steps (the tests use it).
set -uo pipefail

mode=fast
expr=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --fast) mode=fast ;;
        --full) mode=full ;;
        -k)
            if [ "$#" -lt 2 ]; then
                echo "check.sh: -k needs an expression" >&2
                exit 2
            fi
            expr=$2
            shift
            ;;
        *)
            echo "usage: ./check.sh [--fast|--full] [-k EXPR]" >&2
            exit 2
            ;;
    esac
    shift
done

cd "$(dirname "$0")"
export PYTHONPATH="src${PYTHONPATH:+:$PYTHONPATH}"

names=()
codes=()
secs=()
failed=0

# step NAME COMMAND -- COMMAND is run by bash with pipefail, so a failure
# anywhere in a pipe fails the step.
step() {
    local name=$1 cmd=$2 start=$SECONDS code=0
    echo "--- $name ---"
    bash -c "set -o pipefail; $cmd" || code=$?
    names+=("$name")
    codes+=("$code")
    secs+=("$((SECONDS - start))")
    if [ "$code" -ne 0 ]; then
        failed=1
    fi
    echo
}

skip() {
    names+=("$1")
    codes+=("skipped")
    secs+=(0)
}

export CHECK_EXPR=$expr

if [ -n "${CHECK_SH_STEPS_FILE:-}" ]; then
    while IFS=$'\t' read -r name cmd; do
        if [ -n "$name" ]; then
            step "$name" "$cmd"
        fi
    done < "$CHECK_SH_STEPS_FILE"
else
    step ruff "ruff check"
    step mypy "mypy"
    step vulture "vulture"
    step lock-files "python3 -m elysium.scripts.check_lockfiles"
    step import-linter 'PYTHONPATH="$PYTHONPATH:sim" lint-imports'

    if [ -f tools/lint_comments.py ]; then
        step comments "python tools/lint_comments.py --check"
    else
        skip comments
    fi

    if [ -f tools/diffsize.py ]; then
        # Report only: the commit-msg hook is what refuses an oversized commit.
        step diffsize "python tools/diffsize.py || true"
    else
        skip diffsize
    fi

    if [ "$mode" = full ]; then
        step pytest "python -m pytest -q -m 'not integration' \${CHECK_EXPR:+-k \"\$CHECK_EXPR\"}"
    elif [ -n "$expr" ]; then
        step pytest "python -m pytest -q -m 'not integration' -k \"\$CHECK_EXPR\""
    else
        step pytest "python -m pytest tests/unit -q -m 'not integration'"
    fi

    if [ "$mode" = full ]; then
        step controls "python -m elysium.scripts.check_controls"
        step ui "cd ui && npx vitest run && npm run lint"
    else
        step controls "python -m elysium.scripts.check_controls --report-moves"
        step ui "cd ui && npm run lint"
    fi
fi

echo "step | exit | seconds"
echo "-----+------+--------"
for i in "${!names[@]}"; do
    printf '%s | %s | %s\n' "${names[$i]}" "${codes[$i]}" "${secs[$i]}"
done
if [ "$failed" -eq 0 ]; then
    echo "check.sh: all steps passed."
else
    echo "check.sh: one or more steps failed."
fi
exit "$failed"
