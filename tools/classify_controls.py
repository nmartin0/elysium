#!/usr/bin/env python3
"""classify_controls.py -- decide whether a control's break is mechanical.

A control is `mechanical` when its edit is the kind a mutation tester
makes by itself: a condition forced to True or False, a statement
replaced by `pass` or a bare `return`, or one token swapped for another.
Anything else is `semantic`: a break somebody designed for a guarantee.

    classify_controls.py --check          every controls/**/*.toml has the
                                          kind this tool computes (exit 1 if not)
    classify_controls.py --write          set `kind` in those files
    classify_controls.py --convert-legacy convert the records of
                                          src/elysium/scripts/check_controls.py
                                          into controls/legacy/<module>.toml
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLS_DIR = ROOT / "controls"
LEGACY_RUNNER = ROOT / "src" / "elysium" / "scripts" / "check_controls.py"

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


# --- legacy conversion ---------------------------------------------------

#: Which invariant a legacy record's description is about. First match wins;
#: a record that matches nothing is `none`. This is a reading of the sentence,
#: not a proof; REF-19 prunes and re-tags the legacy records.
_INVARIANT_WORDS = (
    ("I6", re.compile(r"\berasure\b|\berase[sd]?\b|\berasing\b|right to be forgotten", re.I)),
    ("I7", re.compile(r"read[- ]only", re.I)),
    ("I5", re.compile(r"re-?authori[sz]|approv(?:al|er|ed|e)\b.*\b(?:grant|revok|permission)", re.I)),
    ("I1", re.compile(r"\buniform\b|indistinguishable|\bis a 404\b|\b404\b|not found.*not allowed", re.I)),
    ("I3", re.compile(r"\bwithheld\b|\bhidden\b|\bmac\b|\blabels?\b|\bclearance\b|may not see|cannot see", re.I)),
)


def guess_invariant(describes: str) -> str:
    for name, pattern in _INVARIANT_WORDS:
        if pattern.search(describes):
            return name
    return "none"


def module_name(path: str) -> str:
    """`src/elysium/core/x.py` -> `elysium.core.x`; `sim/a/b.py` -> `sim.a.b`."""
    stem = path[4:] if path.startswith("src/") else path
    return re.sub(r"\.[A-Za-z0-9]+$", "", stem).replace("/", ".")


def toml_string(text: str) -> str:
    """A TOML string that reads back as exactly `text`."""
    plain = all(ch == "\n" or ch == "\t" or ord(ch) >= 32 and ch != "\x7f" for ch in text)
    if "\n" in text and plain and "'''" not in text and not text.endswith("''"):
        return "'''\n" + text + "'''"
    if "\n" not in text and plain and "'" not in text:
        return "'" + text + "'"
    return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007f")


def render_record(record: dict) -> str:
    tests = "[\n" + "".join(f"    {toml_string(t)},\n" for t in record["tests"]) + "]"
    lines = [
        "[[control]]",
        f"id = {toml_string(record['id'])}",
        f"describes = {toml_string(record['describes'])}",
        f"invariant = {toml_string(record['invariant'])}",
        f"kind = {toml_string(record['kind'])}",
        f"path = {toml_string(record['path'])}",
        f"old = {toml_string(record['old'])}",
        f"new = {toml_string(record['new'])}",
        f"tests = {tests}",
        'expect = "fails"',
    ]
    return "\n".join(lines) + "\n"


def convert_legacy(out_dir: Path, runner: Path = LEGACY_RUNNER) -> dict[str, int]:
    """Write controls/legacy/<module>.toml for every record of the old runner."""
    import importlib.util
    import tomllib

    spec = importlib.util.spec_from_file_location("legacy_check_controls", runner)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    files: dict[str, list[dict]] = {}
    for number, control in enumerate(module.CONTROLS, start=1):
        record = {
            "id": f"LEG-{number:04d}",
            "describes": control.describes,
            "invariant": guess_invariant(control.describes),
            "kind": classify(control.old, control.new),
            "path": control.path,
            "old": control.old,
            "new": control.new,
            "tests": list(control.tests),
        }
        files.setdefault(module_name(control.path), []).append(record)

    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, records in sorted(files.items()):
        text = "\n".join(render_record(r) for r in records)
        back = tomllib.loads(text)["control"]
        for original, parsed in zip(records, back, strict=True):
            if original != {k: parsed[k] for k in original}:
                raise SystemExit(f"{name}: record {original['id']} does not round-trip through TOML")
        (out_dir / f"{name}.toml").write_text(text)
        counts[name] = len(records)
    return counts


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
    group.add_argument("--convert-legacy", action="store_true")
    args = parser.parse_args(argv)

    if args.convert_legacy:
        counts = convert_legacy(CONTROLS_DIR / "legacy")
        print(f"wrote {len(counts)} files, {sum(counts.values())} controls")
        return 0

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
