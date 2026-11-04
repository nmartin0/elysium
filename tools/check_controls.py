#!/usr/bin/env python3
"""check_controls.py -- prove the tests would notice.

A control is one declared break: a file, an exact text and its
replacement, and the tests that must fail while the break is applied.
The runner applies the break, runs those tests and expects FAILURE. A
control that passes is the finding: either the break is not the break it
claims, or the tests do not check what they appear to.

Controls live in controls/<area>/<CARD-ID>.toml (legacy ones in
controls/legacy/<module>.toml), as `[[control]]` tables with the fields
id, describes, invariant (I1..I8, a supporting invariant name or none),
kind (semantic or mechanical), path, old, new, tests and expect = "fails".

    check_controls.py                   fire every control
    --area A / --card ID / --kind K     fire only those (a card is a file stem)
    --only TEXT                         fire those whose description has TEXT
    --summary                           count controls and anchors, run nothing
    --coverage                          I1-I8 against live controls; exit 1 if
                                        an invariant has none; run nothing
    --report-moves / --rewrite-paths    list, or fix, anchors that moved

A control passes only if pytest exits with failure (exit 1) and every
cited test exists. An anchor is found by content: when `path` no longer
holds `old` exactly once, the governed tree is searched. A vanished
anchor is "retired" and needs an explicit deletion of the control.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLS_DIR = ROOT / "controls"
#: Where a break's original text is parked while it is applied, so a run
#: that is killed mid-control can put the file back on the next run.
IN_PROGRESS = ROOT / ".controls-in-progress.json"

KINDS = ("semantic", "mechanical")
INVARIANTS = tuple(f"I{n}" for n in range(1, 9))
SEARCH_ROOTS = ("src", "sdk", "sim", "install", "templates", "scripts", "tools", "ui/src", "ui/packages")
SEARCH_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".json", ".yaml", ".yml", ".sql", ".toml", ".sh")
_SKIP_PARTS = {"node_modules", "__pycache__", ".git", "dist", "build", ".venv"}
OK, MOVED, RETIRED, AMBIGUOUS = "ok", "MOVED", "RETIRED", "AMBIGUOUS"
FIRES, SILENT, BROKEN = "fires", "silent", "broken"
_FIELDS = {"id", "describes", "invariant", "kind", "path", "old", "new", "tests", "expect"}


@dataclass(frozen=True)
class Control:
    id: str
    invariant: str
    kind: str
    path: str
    old: str
    new: str
    tests: list[str]
    describes: str = ""
    area: str = ""
    card: str = ""
    file: str = ""
    expect: str = "fails"


def load_controls(directory: Path | None = None) -> list[Control]:
    """Every control under controls/, validated; ValueError on a malformed one."""
    base = directory or CONTROLS_DIR
    found: list[Control] = []
    seen: set[str] = set()
    for file in sorted(base.rglob("*.toml")):
        where = file.relative_to(base)
        for record in tomllib.loads(file.read_text()).get("control", []):
            missing = _FIELDS - {"describes"} - record.keys()
            if missing or record.keys() - _FIELDS:
                raise ValueError(f"{where}: bad fields {sorted(missing | (record.keys() - _FIELDS))}")
            name = record["id"]
            if name in seen:
                raise ValueError(f"{where}: id {name} is used twice")
            seen.add(name)
            if record["kind"] not in KINDS:
                raise ValueError(f"{where}: {name}: kind must be one of {KINDS}")
            if record["expect"] != "fails":
                raise ValueError(f"{where}: {name}: expect must be 'fails'")
            named = re.fullmatch(r"[a-z][a-z0-9-]+", record["invariant"])
            if record["invariant"] not in (*INVARIANTS, "none") and not named:
                raise ValueError(f"{where}: {name}: invariant must be I1..I8, a name or none")
            if not record["tests"] or not all("::" in t for t in record["tests"]):
                raise ValueError(f"{where}: {name}: tests must be individual test ids")
            found.append(Control(
                area=where.parent.name, card=where.stem, file=str(file),
                **{k: record[k] for k in _FIELDS - {"describes"}},
                describes=record.get("describes", name)))
    return found


# --- anchors --------------------------------------------------------------

def _count_in(path: Path, old: str) -> int:
    try:
        return path.read_text().count(old)
    except (OSError, UnicodeDecodeError):
        return 0


def _governed_files() -> list[Path]:
    found = []
    for name in SEARCH_ROOTS:
        base = ROOT / name
        if base.is_dir():
            for file in base.rglob("*"):
                if (file.suffix in SEARCH_SUFFIXES and file.is_file()
                        and not _SKIP_PARTS.intersection(file.relative_to(ROOT).parts)):
                    found.append(file)
    return sorted(found)


def resolve(control: Control, files: list[Path] | None = None) -> tuple[str, list[str]]:
    """Where the anchor is now, as (status, paths).

    OK: `path` holds `old` exactly once. MOVED: it does not, and exactly one
    governed file holds it exactly once. RETIRED: nowhere. AMBIGUOUS: several
    files, or more than once. Only OK may count as firing.
    """
    if _count_in(ROOT / control.path, control.old) == 1:
        return OK, [control.path]
    hits = {}
    for file in files if files is not None else _governed_files():
        count = _count_in(file, control.old)
        if count:
            hits[str(file.relative_to(ROOT))] = count
    if not hits:
        return RETIRED, []
    if len(hits) == 1 and sum(hits.values()) == 1:
        return MOVED, list(hits)
    return AMBIGUOUS, sorted(hits)


def resolve_all(controls: list[Control]) -> list[tuple[Control, str, list[str]]]:
    files: list[Path] | None = None
    resolved = []
    for control in controls:
        if _count_in(ROOT / control.path, control.old) != 1 and files is None:
            files = _governed_files()
        status, paths = resolve(control, files)
        resolved.append((control, status, paths))
    return resolved


def describe_problem(control: Control, status: str, paths: list[str]) -> str:
    label = f"{control.id} ({control.describes})"
    if status == MOVED:
        return f"{control.path} -> {paths[0]}   {label}"
    if status == RETIRED:
        return (f"{control.path}: the text this control breaks is nowhere in the governed tree; "
                f"delete the control or re-anchor it   {label}")
    return (f"{control.path}: the text is in {len(paths)} places ({', '.join(paths[:4])}); "
            f"make `old` longer so it is unique   {label}")


def rewrite_paths(text: str, moves: dict[str, str]) -> tuple[str, int]:
    """Change only the `path =` line of the records whose id is in `moves`."""
    lines = text.splitlines(keepends=True)
    count = 0
    current = None
    for number, line in enumerate(lines):
        match = re.match(r'id = [\'"]([^\'"]+)[\'"]', line)
        if match:
            current = match.group(1)
        elif current in moves and line.startswith("path = "):
            lines[number] = f'path = "{moves[current]}"\n'
            count += 1
            current = None
    return "".join(lines), count


# --- breaking and running -------------------------------------------------

def restore_anything_left_behind() -> list[str]:
    if not IN_PROGRESS.exists():
        return []
    try:
        parked = json.loads(IN_PROGRESS.read_text())
    except (OSError, ValueError):
        raise SystemExit(
            f"{IN_PROGRESS} is unreadable, and it means a break may still be applied. "
            f"Check `git status` before running anything.") from None
    for path, original in parked.items():
        (ROOT / path).write_text(original)
    IN_PROGRESS.unlink()
    return list(parked)


def apply(control: Control) -> str:
    """Break the code, returning what was there before."""
    path = ROOT / control.path
    original = path.read_text()
    occurrences = original.count(control.old)
    if occurrences != 1:
        raise SystemExit(
            f"{control.path}: the break for {control.id} matches {occurrences} times, not once. "
            f"A break that matches nothing runs the UNMODIFIED code and passes.")
    # Parked BEFORE the break goes in, so a kill between the two leaves the file untouched.
    IN_PROGRESS.write_text(json.dumps({control.path: original}))
    path.write_text(original.replace(control.old, control.new))
    return original


_PYTEST_EXIT = {
    0: "all the tests passed",
    1: "tests failed",
    2: "the run was interrupted, or collection failed (the break may have made a test module unimportable)",
    3: "pytest hit an internal error",
    4: "pytest was used wrongly: usually a test id that does not exist",
    5: "no tests were collected",
}


def classify(returncode: int) -> tuple[str, str]:
    """A pytest exit status as (outcome, why). Only 1 shows a control fired."""
    if returncode == 1:
        return FIRES, _PYTEST_EXIT[1]
    if returncode == 0:
        return SILENT, _PYTEST_EXIT[0]
    return BROKEN, f"pytest exited {returncode}: " + _PYTEST_EXIT.get(returncode, "an unknown status")


def run(control: Control) -> tuple[str, str]:
    """Run the control's tests, expecting them to fail: (FIRES|SILENT|BROKEN, output)."""
    # No bytecode written from broken code: two breaks of one file that change its size
    # by the same amount within a second would otherwise run the first break's .pyc.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *control.tests, "-q", "--no-header", "-x"],
        cwd=ROOT, capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    outcome, why = classify(result.returncode)
    output = (result.stdout or result.stderr).strip()
    if outcome == SILENT and " skipped" in output and " passed" not in output:
        outcome, why = BROKEN, "every cited test was skipped (a missing binary or service?)"
    if outcome == BROKEN:
        output = f"{why}\n{output}"
    return outcome, output


# --- reports --------------------------------------------------------------

def summary(controls: list[Control], resolved: list[tuple[Control, str, list[str]]]) -> str:
    def table(title: str, values: list[str]) -> list[str]:
        counts: dict[str, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return [f"{title}:"] + [f"  {key:<12} {counts[key]}" for key in sorted(counts)]

    statuses = [s for _, s, _ in resolved]
    lines = [f"controls: {len(controls)}"]
    lines += table("anchors", statuses)
    lines += table("kind", [c.kind for c in controls])
    lines += table("area", [c.area for c in controls])
    lines += table("invariant", [c.invariant for c in controls])
    return "\n".join(lines)


def coverage(resolved: list[tuple[Control, str, list[str]]]) -> tuple[str, bool]:
    live = [c for c, status, _ in resolved if status in (OK, MOVED)]
    rows, ok = [], True
    for name in INVARIANTS:
        count = sum(1 for c in live if c.invariant == name)
        ok = ok and count > 0
        rows.append(f"  {name}  {count:>4} live control(s){'' if count else '   <-- none'}")
    return "\n".join(["invariant coverage:", *rows]), ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the negative controls actually fire.")
    parser.add_argument("--area")
    parser.add_argument("--card")
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--only", help="fire controls whose description contains this")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--report-moves", action="store_true")
    parser.add_argument("--rewrite-paths", action="store_true")
    args = parser.parse_args(argv)

    for path in restore_anything_left_behind():
        print(f"  restored {path}, left broken by a run that was killed")

    try:
        everything = load_controls()
    except ValueError as error:
        print(f"controls: {error}", file=sys.stderr)
        return 2
    controls = [c for c in everything
                if (not args.area or c.area == args.area)
                and (not args.card or c.card == args.card)
                and (not args.kind or c.kind == args.kind)
                and (not args.only or args.only.lower() in c.describes.lower())]
    if not controls:
        if args.card and not (args.area or args.kind or args.only):
            print(f"card {args.card} has no controls")
            return 0
        print("no control matches", file=sys.stderr)
        return 1

    resolved = resolve_all(controls)
    moved = [(c, p[0]) for c, status, p in resolved if status == MOVED]
    unresolved = [(c, status, p) for c, status, p in resolved if status in (RETIRED, AMBIGUOUS)]

    if args.summary:
        print(summary(controls, resolved))
        return 1 if unresolved else 0
    if args.coverage:
        text, ok = coverage(resolve_all(everything))
        print(text)
        return 0 if ok else 1
    if args.report_moves or args.rewrite_paths:
        for control, new_path in moved:
            print(f"  MOVED      {describe_problem(control, MOVED, [new_path])}")
        for control, status, paths in unresolved:
            print(f"  {status:<10} {describe_problem(control, status, paths)}")
        if args.rewrite_paths and moved:
            for file in sorted({c.file for c, _ in moved}):
                mine = {c.id: p for c, p in moved if c.file == file}
                text, count = rewrite_paths(Path(file).read_text(), mine)
                Path(file).write_text(text)
                print(f"rewrote {count} path(s) in {file}")
        elif not moved and not unresolved:
            print("every control's anchor is where it says.")
        return 1 if unresolved or (moved and not args.rewrite_paths) else 0

    new_paths = {c.id: p[0] for c, status, p in resolved if status == MOVED}
    skipped = {c.id for c, _, _ in unresolved}
    silent, broken = [], []
    fired = 0
    for control in controls:
        if control.id in skipped:
            continue
        if control.id in new_paths:
            control = replace(control, path=new_paths[control.id])
        original = apply(control)
        try:
            outcome, output = run(control)
        finally:
            (ROOT / control.path).write_text(original)
            IN_PROGRESS.unlink(missing_ok=True)
        label = f"{control.id} {control.describes}"
        if outcome == FIRES and control.id in new_paths:
            print(f"  MOVED   {label} (now {control.path}; run --rewrite-paths)")
        elif outcome == FIRES:
            fired += 1
            print(f"  fires   {label}")
        elif outcome == BROKEN:
            broken.append(control)
            print(f"  BROKEN  {label}")
            print(f"          {output.splitlines()[0] if output else ''}")
            print("          this does NOT show the tests notice the break")
        else:
            silent.append(control)
            print(f"  SILENT  {label}")
            print(f"          broke {control.path} and the tests still passed")
            print(f"          {output.splitlines()[-1] if output else ''}")

    print()
    for control, status, paths in unresolved:
        print(f"  {status:<9} {describe_problem(control, status, paths)}")
    if moved:
        print(f"{len(moved)} control(s) moved: their path is stale. Run with --rewrite-paths.")
    if unresolved:
        print(f"{len(unresolved)} control(s) were not run: their anchor vanished or is ambiguous, "
              f"which needs an explicit decision.")
    if broken:
        print(f"{len(broken)} control(s) could not be run: pytest did not report a failed test, "
              f"so nothing is known about them.")
    if silent:
        print(f"{len(silent)} control(s) did not fire. Either the break is not the break it claims, "
              f"or the tests do not check what they appear to -- and it is usually the second.")
    print(f"fired {fired} of {len(controls)}; silent {len(silent)}, broken {len(broken)}, "
          f"moved {len(moved)}, retired or ambiguous {len(unresolved)}")
    if silent or broken or moved or unresolved:
        return 1
    print(f"All {len(controls)} controls fire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
