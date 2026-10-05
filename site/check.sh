#!/usr/bin/env bash
# The site's own gate.
#
# THE WEBSITE TAKES RESPONSIBILITY FOR ITSELF. Its tests used to live
# in Elysium's tests/unit/ and its HTMLParser override needed an entry
# in Elysium's vulture whitelist -- so a typo in a marketing headline
# could fail the product's suite, and the product carried a line of
# configuration that existed only for a web page.
#
# That is backwards. This directory is the website FOR Elysium, not
# part of Elysium, and it is meant to be liftable into its own
# repository without leaving anything behind.
#
# Run it from anywhere:   bash site/check.sh
set -euo pipefail
cd "$(dirname "$0")"
echo "--- site ---"
python -m pytest tests -q
echo
echo "Serve it with:  python -m http.server 8080"
