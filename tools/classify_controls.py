#!/usr/bin/env python3
"""classify_controls.py -- decide whether a control's break is mechanical.

A control is `mechanical` when its edit is the kind a mutation tester
makes by itself: a condition forced to True or False, a statement
replaced by `pass` or a bare `return`, or one token swapped for another.
Anything else is `semantic`: a break somebody designed for a guarantee.

    classify_controls.py --check          every controls/**/*.toml has the
                                          kind this tool computes (exit 1 if not)
    classify_controls.py --write          set `kind` in those files
"""

from __future__ import annotations

import argparse
import difflib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLS_DIR = ROOT / "controls"

_TOKEN = re.compile(r"[A-Za-z_]\w*|\d+(?:\.\d+)?|\"[^\"\n]*\"|'[^'\n]*'|[<>=!]=|\*\*|//|->|:=|<<|>>|[-+*/%&|^]=|\S")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def classify(old: str, new: str) -> str:
    """`mechanical` or `semantic` for the edit old -> new."""
    after = _tokens(new)
    if after in (["pass"], ["return"], ["True"], ["False"]):
        return "mechanical"
    before = _tokens(old)
    blocks = [op for op in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
              if op[0] != "equal"]
    if len(blocks) != 1:
        return "semantic"
    tag, i1, i2, j1, j2 = blocks[0]
    replacement = after[j1:j2]
    if tag == "replace" and replacement in (["True"], ["False"], ["pass"], ["return"]):
        return "mechanical"
    if tag == "replace" and i2 - i1 == 1 and j2 - j1 == 1:
        return "mechanical"
    return "semantic"


# --- check / write -------------------------------------------------------

def _files() -> list[Path]:
    return sorted(CONTROLS_DIR.rglob("*.toml"))


def _kind_lines(path: Path) -> list[tuple[str, str, int]]:
    """(id, kind now, index of its `kind =` line) for each record of the file."""
    import tomllib

    text = path.read_text()
    records = tomllib.loads(text)["control"]
    lines = text.splitlines()
    found = []
    index = 0
    for record in records:
        while not lines[index].startswith("[[control]]"):
            index += 1
        k = index
        while not lines[k].startswith("kind = "):
            k += 1
        found.append((record["id"], record["kind"], k))
        index = k
    return found


def _computed(path: Path) -> dict[str, str]:
    import tomllib

    return {r["id"]: classify(r["old"], r["new"]) for r in tomllib.loads(path.read_text())["control"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)

    wrong = 0
    for path in _files():
        want = _computed(path)
        lines = path.read_text().splitlines(keepends=True)
        changed = False
        for control_id, now, line in _kind_lines(path):
            if now != want[control_id]:
                wrong += 1
                if args.write:
                    lines[line] = f'kind = "{want[control_id]}"\n'
                    changed = True
                else:
                    print(f"{path.relative_to(ROOT)}: {control_id} is {now}, should be {want[control_id]}")
        if changed:
            path.write_text("".join(lines))
    if args.write:
        print(f"set {wrong} kind(s)")
        return 0
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
