#!/bin/sh
# lint.sh  (runs Ruff, MyPy, and Vulture -- the three code-quality
# tools this project uses, and why each one earns its place)
#
# Three genuinely different, non-overlapping questions, not three
# tools bolted on for their own sake:
#   Ruff   -- is this code well-formed, locally? (unused imports,
#             undefined names, real Python gotchas, import order,
#             syntax modernization -- all local, per-file scope)
#   MyPy   -- do the types flowing through this code actually agree
#             with each other? (the only one of the three that
#             understands data SHAPE, not just whether names are used)
#   Vulture -- does anything in the rest of the codebase still use
#             this, at all? (whole-program analysis -- catches an old
#             helper nothing calls anymore, which Ruff structurally
#             cannot: confirmed via Ruff's own GitHub issue #872,
#             still open, acknowledging this as a real, unsolved
#             architectural gap in their per-file design)
#
# All three configured in pyproject.toml -- bare invocations here,
# same as a developer would run locally. Deliberately NOT running
# `ruff format` -- see pyproject.toml's own [tool.ruff] docstring for
# why the reformatting trade-off against this project's own,
# deliberately hand-placed formatting stays a separate decision, not
# bundled into this script silently.
#
# Runs all three regardless of earlier failures (so one full run shows
# every real issue at once, not just the first tool's), but exits
# non-zero if ANY of them found something -- correct for CI use, where
# "some checks passed" must still fail the build.
#
# Run from the project root:
#   ./lint.sh

set -u
STATUS=0

echo "--- ruff check ---"
ruff check || STATUS=1

echo
echo "--- mypy ---"
mypy || STATUS=1

echo
echo "--- vulture ---"
vulture || STATUS=1

echo
if [ "$STATUS" -eq 0 ]; then
    echo "All checks passed."
else
    echo "One or more checks failed -- see above."
fi
exit "$STATUS"
