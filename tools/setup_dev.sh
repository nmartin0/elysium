#!/usr/bin/env bash
# setup_dev.sh -- make a development environment and show how to turn the hooks on.
#
#   tools/setup_dev.sh            print what to run
#   tools/setup_dev.sh --apply    run it
#
# The hooks live in .githooks/; git uses them once core.hooksPath points there.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

commands=(
    "uv sync --extra dev"
    "git config core.hooksPath .githooks"
    "(cd shell && npm ci) && (cd ui && npm ci)"
)

if [ "${1:-}" = "--apply" ]; then
    for command in "${commands[@]}"; do
        echo "+ $command"
        bash -c "$command"
    done
    exit 0
fi

echo "Run these from the repository root (or: tools/setup_dev.sh --apply):"
for command in "${commands[@]}"; do
    echo "    $command"
done
