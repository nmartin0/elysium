#!/usr/bin/env python3
"""rerun_report.py -- run again the commands a worker's report claims to have run.

    rerun_report.py REPORT [--worktree DIR] [--heavy SCRIPT]

Section 3 of a report lists every command, one per line, as
`<command>` -> exit <N>  (section 1.1). Each is run in DIR (default: the
current directory) through tools/heavy.sh and the claimed exit status is
compared with the real one. A table is printed (command, claimed, actual).
Exit 1 when any differ, or when the report has no section 3 or no command.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAIM = re.compile(r"^\s*(?:[-*]\s*)?`(?P<cmd>[^`]+)`\s*(?:->|→)\s*exit\s+(?P<code>\d+)\b")
SECTION_3 = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?3[.)]")
SECTION_4 = re.compile(r"^\s*(?:#+\s*)?(?:\*\*)?4[.)]")


def claims(report: str) -> list[tuple[str, int]]:
    """The (command, exit status) pairs of section 3."""
    out: list[tuple[str, int]] = []
    inside = False
    for line in report.splitlines():
        if not inside:
            inside = bool(SECTION_3.match(line))
            if not inside:
                continue
        elif SECTION_4.match(line):
            break
        m = CLAIM.match(line)
        if m:
            out.append((m.group("cmd"), int(m.group("code"))))
    return out


def rerun(cmd: str, number: int, worktree: Path, heavy: Path) -> int:
    result = subprocess.run(  # noqa: S603 -- the command is the worker's, run on purpose in its worktree
        [str(heavy), f"rerun-{number}", "bash", "-c", cmd],
        cwd=worktree, capture_output=True, text=True, check=False)
    return result.returncode


def table(rows: list[tuple[str, int, int]]) -> str:
    width = max([len(c) for c, _, _ in rows] + [7])
    lines = [f"{'command'.ljust(width)}  claimed  actual"]
    for cmd, claimed, actual in rows:
        mark = "" if claimed == actual else "  DIFFERS"
        lines.append(f"{cmd.ljust(width)}  {claimed:>7}  {actual:>6}{mark}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("report", type=Path)
    parser.add_argument("--worktree", type=Path, default=Path.cwd())
    parser.add_argument("--heavy", type=Path, default=ROOT / "tools" / "heavy.sh")
    args = parser.parse_args(argv)
    found = claims(args.report.read_text())
    if not found:
        print("rerun_report: no command with a claimed exit status in section 3", file=sys.stderr)
        return 1
    rows = [(cmd, claimed, rerun(cmd, n, args.worktree, args.heavy))
            for n, (cmd, claimed) in enumerate(found, 1)]
    print(table(rows))
    return 0 if all(c == a for _, c, a in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
