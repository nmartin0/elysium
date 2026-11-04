#!/usr/bin/env python3
"""diffsize.py -- how big is a commit, in lines a person has to read.

Added plus deleted lines per commit, leaving out generated paths (locks,
openapi.json, schema.d.ts, docs/reference, controls, quality). A commit
should stay within about 400; over 1,000 is refused unless its message
has a `Large-change: <reason>` line (N32).

    diffsize.py [--base REF]       every commit in REF..HEAD (default: dev,
                                   or the last commit when there is no dev)
    diffsize.py --commit-msg FILE  the staged change against the message in FILE
                                   (for the commit-msg hook)

Exit: 0 fine; 8 a commit is over 1,000 lines without a Large-change line.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
GUIDELINE = 400
LIMIT = 1000
EXIT_TOO_BIG = 8
GENERATED = (
    "*.lock", "*package-lock.json", "*openapi.json", "*schema.d.ts",
    "docs/reference/*", "controls/*", "quality/*",
)
_LARGE = re.compile(r"^Large-change:\s*\S", re.M)


class Size(NamedTuple):
    added: int
    deleted: int

    @property
    def total(self) -> int:
        return self.added + self.deleted


def is_generated(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in GENERATED)


def _git(*arguments: str) -> str:
    return subprocess.run(  # noqa: S603, S607 -- fixed argument list, no shell
        ["git", *arguments], capture_output=True, text=True, check=True, cwd=ROOT).stdout  # noqa: S607 -- fixed command


def parse_numstat(output: str) -> Size:
    """Size of a `git ... --numstat -z` output, generated paths left out."""
    fields = output.split("\0")
    added = deleted = 0
    index = 0
    while index < len(fields) and fields[index]:
        head = fields[index].split("\t")
        if len(head) == 3 and head[2] == "":  # a rename: counts, then old and new path
            path = fields[index + 2]
            index += 3
        else:
            path = head[2]
            index += 1
        if head[0] != "-" and not is_generated(path):
            added += int(head[0])
            deleted += int(head[1])
    return Size(added, deleted)


def commit_size(sha: str) -> Size:
    return parse_numstat(_git("show", "--numstat", "-z", "-M", "--format=", sha))


def staged_size() -> Size:
    return parse_numstat(_git("diff", "--cached", "--numstat", "-z", "-M"))


def has_large_change(message: str) -> bool:
    return bool(_LARGE.search(message))


def too_big(size: Size, message: str) -> bool:
    return size.total > LIMIT and not has_large_change(message)


def _commits(base: str) -> list[str]:
    return _git("rev-list", "--reverse", "--no-merges", f"{base}..HEAD").split()


def _default_base() -> str:
    for candidate in ("dev", "origin/dev"):
        if subprocess.run(  # noqa: S603, S607 -- fixed argument list, no shell
                ["git", "rev-parse", "--verify", "-q", candidate], capture_output=True,  # noqa: S607 -- fixed command
                check=False, cwd=ROOT).returncode == 0:
            return _git("merge-base", candidate, "HEAD").strip()
    return "HEAD~1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--base")
    parser.add_argument("--commit-msg", metavar="FILE")
    args = parser.parse_args(argv)

    if args.commit_msg:
        message = "\n".join(line for line in Path(args.commit_msg).read_text().splitlines()
                            if not line.startswith("#"))
        size = staged_size()
        if too_big(size, message):
            print(f"diffsize: this commit changes {size.total} lines ({size.added} added, "
                  f"{size.deleted} deleted, generated paths left out); over {LIMIT} needs a "
                  f"`Large-change: <reason>` line, and about {GUIDELINE} is the target.", file=sys.stderr)
            return EXIT_TOO_BIG
        return 0

    status = 0
    for sha in _commits(args.base or _default_base()):
        size = commit_size(sha)
        message = _git("show", "-s", "--format=%B", sha)
        subject = message.splitlines()[0] if message.strip() else ""
        verdict = "ok"
        if too_big(size, message):
            verdict, status = "TOO BIG: needs Large-change", EXIT_TOO_BIG
        elif size.total > GUIDELINE:
            verdict = "over the guideline" + (" (Large-change given)" if has_large_change(message) else "")
        print(f"{sha[:8]}  +{size.added:<5} -{size.deleted:<5} {size.total:>5}  {verdict}  {subject[:50]}")
    return status


if __name__ == "__main__":
    sys.exit(main())
