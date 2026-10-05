#!/usr/bin/env bash
# The site's own gate.
#
# THE WEBSITE TAKES RESPONSIBILITY FOR ITSELF. Its tests used to live
# in Elysium's tests/unit/, its HTMLParser override needed a line in
# Elysium's vulture whitelist, and ruff still reached in here after
# both were fixed -- a `zip()` in THIS file failed ELYSIUM's gate.
#
# So Elysium's ruff now excludes `site`, and the site lints itself.
# Excluding without replacing would have been a loophole rather than a
# separation.
#
# Run from anywhere:   bash site/check.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "--- site: lint ---"
ruff check tests --line-length 100

echo "--- site: tests ---"
# tests/test_rendered.py runs a real browser and measures the page.
# It skips cleanly where none is installed. Everything it checks
# shipped broken once and was invisible to the string tests.
python -m pytest tests -q

echo
echo "Serve it with:  python -m http.server 8080"
