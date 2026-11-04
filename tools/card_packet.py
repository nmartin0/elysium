#!/usr/bin/env python3
"""card_packet.py -- the bundle a worker gets for one card.

    card_packet.py ID               a card, e.g. ADM-03a
    card_packet.py T0.5 3b          one step of a Tier 0 item (the step is marked)
    card_packet.py --roadmap FILE ID

Prints, in order: section 1.1 (the brief), 1.3 (the parallel rules), 1.4
(conventions), the card's workstream introduction (section 5, up to its first
card), the card itself, and every contract its header names (section 3, by
anchor). For a Tier 0 item the workstream introduction is left out.
Exit 1 when the card, a contract or a step does not exist.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "roadmap.md"
STEP_MARK = ">>> "
MARKED_AFTER = "(this is the step you are asked to do; the rest of the item is context)"


def _until(lines: list[str], start: int, stops: tuple[str, ...]) -> list[str]:
    end = next((n for n in range(start + 1, len(lines)) if lines[n].startswith(stops)), len(lines))
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _heading(lines: list[str], prefix: str) -> int:
    for n, line in enumerate(lines):
        if line.startswith(prefix):
            return n
    raise LookupError(f"no heading starting {prefix!r}")


def subsection(lines: list[str], number: str) -> list[str]:
    return _until(lines, _heading(lines, f"### {number} "), ("### ", "## "))


def workstream_intro(lines: list[str], prefix: str) -> list[str]:
    table = next(line for line in lines if re.match(rf"^\| {prefix}: ", line))
    number = [c.strip() for c in table.split("|")][2]
    return _until(lines, _heading(lines, f"### {number} "), ("#### ", "### ", "## "))


def item(lines: list[str], cid: str) -> list[str]:
    for n, line in enumerate(lines):
        if line.startswith(f"#### {cid} · ") or line.startswith(f"### {cid} "):
            return _until(lines, n, ("#### ", "### ", "## "))
    raise LookupError(f"no card or item {cid}")


def contract(lines: list[str], cid: str) -> list[str]:
    start = _heading(lines, f'<a id="{cid.lower()}"></a>')
    return _until(lines, start, ('<a id="', "## "))


def mark_step(body: list[str], step: str) -> list[str]:
    """Prefix the lines of step `step` (`3b`; `3` takes 3a, 3b too) with a marker."""
    label = re.compile(r"^  (\d+)([a-z]?)\. ")
    out, active, found = [], False, False
    for line in body:
        m = label.match(line)
        if m:
            active = (m.group(1) + m.group(2)) == step or (step.isdigit() and m.group(1) == step)
            found = found or active
        elif line and not line.startswith("   ") and not line.startswith("  "):
            active = active and not line.startswith("- ")
        out.append((STEP_MARK + line) if active else line)
    if not found and re.fullmatch(r"\d+[a-z]", step):
        return mark_step(body, step[:-1])  # 3a and 3b are two commits of step 3
    if not found:
        raise LookupError(f"no step {step}")
    return out


def packet(text: str, cid: str, step: str | None = None) -> str:
    lines = text.splitlines()
    parts = [subsection(lines, "1.1"), subsection(lines, "1.3"), subsection(lines, "1.4")]
    body = item(lines, cid)
    header = next((i for i, line in enumerate(body) if line == "```card"), None)
    contracts: list[str] = []
    if header is not None:
        block = body[header + 1:body.index("```", header + 1)]
        for line in block:
            if line.startswith("contracts: ") and line != "contracts: -":
                contracts = [c.strip() for c in line[len("contracts: "):].split(",")]
    if not cid.startswith("T0."):
        parts.append(workstream_intro(lines, cid.split("-")[0]))
    elif step:
        body = mark_step(body, step)
        body.insert(1, f"{STEP_MARK}STEP {step} {MARKED_AFTER}")
    parts.append(body)
    parts += [contract(lines, c) for c in contracts]
    return "\n\n".join("\n".join(p) for p in parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("id")
    parser.add_argument("step", nargs="?", help="a step of a Tier 0 item, e.g. 3b")
    parser.add_argument("--roadmap", type=Path, default=ROADMAP)
    args = parser.parse_args(argv)
    if args.step and not args.id.startswith("T0."):
        print("card_packet: a step is only for a Tier 0 item", file=sys.stderr)
        return 1
    try:
        sys.stdout.write(packet(args.roadmap.read_text(), args.id, args.step))
    except (LookupError, ValueError, StopIteration) as error:
        print(f"card_packet: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
