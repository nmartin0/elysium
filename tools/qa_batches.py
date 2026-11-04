#!/usr/bin/env python3
"""qa_batches.py -- today's broad handlers and comment hits, in batches.

    qa_batches.py err      [--batch N] [--check]
    qa_batches.py comments [--batch N] [--check]

`err` takes the BLE and S ruff hits listed in quality/ruff-ignores.txt;
`comments` takes the hits of tools/lint_comments.py in the baseline. Hits are
grouped by directory: a batch holds the files of one directory, at most 15
handlers (err) or 80 hits (comments); a single file over the limit is a batch
of its own. Without --batch every batch is printed, one per line:
`N<TAB>directory<TAB>hits<TAB>files`. With --batch N the batch's files are
printed, one per line.

--check (needs --batch) counts the batch's hits again and exits 1 when any
is left.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

LIMITS = {"err": 15, "comments": 80}


def err_hits() -> Counter[str]:
    import ruff_baseline

    hits: Counter[str] = Counter()
    for (path, rule), n in ruff_baseline.read_baseline().items():
        if rule.startswith(("BLE", "S")) and rule != "S101":
            hits[path] += n
    return hits


def comment_hits() -> Counter[str]:
    import lint_comments

    hits: Counter[str] = Counter()
    for key, n in lint_comments.read_baseline().items():
        hits[key.rsplit(":", 1)[0]] += n
    return hits


def batches(hits: Counter[str], limit: int) -> list[tuple[str, int, list[str]]]:
    """(directory, hits, files) with files of one directory, at most `limit` hits."""
    by_dir: dict[str, list[str]] = {}
    for path in sorted(hits):
        by_dir.setdefault(str(PurePosixPath(path).parent), []).append(path)
    out: list[tuple[str, int, list[str]]] = []
    for directory in sorted(by_dir):
        files: list[str] = []
        total = 0
        for path in by_dir[directory]:
            if files and total + hits[path] > limit:
                out.append((directory, total, files))
                files, total = [], 0
            files.append(path)
            total += hits[path]
        out.append((directory, total, files))
    return out


def remaining(kind: str, files: list[str]) -> int:
    """Hits still in `files`, counted afresh."""
    if kind == "err":
        import ruff_baseline

        return sum(n for (path, rule), n in ruff_baseline.offenders().items()
                   if path in files and rule.startswith(("BLE", "S")) and rule != "S101")
    import lint_comments

    return sum(len(lint_comments.scan_file(ROOT / path)) for path in files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("kind", choices=sorted(LIMITS))
    parser.add_argument("--batch", type=int)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check and args.batch is None:
        parser.error("--check needs --batch")
    hits = err_hits() if args.kind == "err" else comment_hits()
    listed = batches(hits, LIMITS[args.kind])
    if args.batch is None:
        for n, (directory, total, files) in enumerate(listed, 1):
            print(f"{n}\t{directory}\t{total}\t{len(files)}")
        return 0
    if not 1 <= args.batch <= len(listed):
        print(f"qa_batches: no batch {args.batch}; there are {len(listed)}", file=sys.stderr)
        return 1
    files = listed[args.batch - 1][2]
    if not args.check:
        print("\n".join(files))
        return 0
    left = remaining(args.kind, files)
    if left:
        print(f"qa_batches: {left} hit(s) left in batch {args.batch}", file=sys.stderr)
        return 1
    print(f"qa_batches: batch {args.batch} is clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
