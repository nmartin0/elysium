#!/usr/bin/env python3
"""plan_check.py -- the parallel plan in docs/roadmap.md obeys its own rules.

    plan_check.py [--roadmap FILE]          exit 1, one violation per line
    plan_check.py [--roadmap FILE] --next   cards that can start now

Checked: every card and Tier 0 item has a header block in the fixed format of
section 1.2 (keys, order, values); an id is defined once; every `depends` and
`contracts` id is defined; a dependency is merged before the card's wave opens
(a card in an earlier wave, or a Tier 0 item at or before the wave's opening
item); no two cards of a wave own the same path (`!path` excludes,
`file#section` overlaps only the same section or the whole file); no card owns
a path of the Tier 0 item running beside its wave; the wave table agrees with
the headers.

--next lists the cards that are OPEN, whose `depends` are all DONE and whose
wave is open: its opening Tier 0 item is DONE and every card of the earlier
waves is DONE (a BLOCKED or post-1.0 card does not hold a wave open).
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "roadmap.md"

TIER0 = re.compile(r"^### (T0\.\d+B?) (.*)$")
PREFIXES = "MEAS|SEC|API|ADM|CLI|OPS|INS|DOC|CI|QA|REF|ADD|APP"
CARD_ID = rf"(?:{PREFIXES})-[A-Za-z0-9-]*[A-Za-z0-9]"
CARD_HEADING = re.compile(rf"^#### ({CARD_ID}) · (.+)$")
CONTRACT_HEADING = re.compile(r"^### (C-[A-Z-]*[A-Z]) · (.+)$")
TIER0_IDS = ["T0.1", "T0.1B"] + [f"T0.{n}" for n in range(2, 7)] + ["T0.6B"] + [f"T0.{n}" for n in range(7, 16)]
HEADER_KEYS = ["id", "wave", "status", "size", "model", "depends", "contracts", "owns"]
STATUS = re.compile(r"^(OPEN|IN PROGRESS|DONE [0-9a-f]{7,40}|BLOCKED Q-[A-Z0-9]+|POST-1\.0)$")


class Plan:
    """The headers, contracts and wave table of one roadmap text."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.problems: list[str] = []
        self.table_problems: list[str] = []
        self.headers: dict[str, dict] = {}
        self.contracts = {m.group(1) for m in map(CONTRACT_HEADING.match, self.lines) if m}
        self._read_headers()
        self.waves = self._read_waves()
        self.order = [w[0] for w in self.waves]

    # ---- reading -------------------------------------------------------
    def _section(self, number: int) -> list[str]:
        start = next((n for n, line in enumerate(self.lines) if line.startswith(f"## {number}. ")), None)
        if start is None:
            self.problems.append(f"section {number} is missing")
            return []
        end = next((n for n in range(start + 1, len(self.lines)) if self.lines[n].startswith("## ")),
                   len(self.lines))
        return self.lines[start:end]

    def _read_headers(self) -> None:
        for n, line in enumerate(self.lines):
            m = CARD_HEADING.match(line) or TIER0.match(line)
            if not m:
                continue
            cid = m.group(1)
            if self.lines[n + 1:n + 3] != ["", "```card"]:
                self.problems.append(f"{cid}: no header block directly after its heading")
                continue
            end = next((k for k in range(n + 3, len(self.lines)) if self.lines[k] == "```"), None)
            if end is None:
                self.problems.append(f"{cid}: the header block is not closed")
                continue
            if cid in self.headers:
                self.problems.append(f"{cid}: defined twice")
                continue
            fields = self._parse(cid, self.lines[n + 3:end])
            if fields is not None:
                self.headers[cid] = fields

    def _parse(self, cid: str, raw: list[str]) -> dict | None:
        fields: dict = {}
        owns: list[str] = []
        keys: list[str] = []
        for line in raw:
            if line.startswith("  - "):
                if not keys or keys[-1] != "owns":
                    self.problems.append(f"{cid}: a path outside `owns`: {line!r}")
                    return None
                owns.append(line[4:])
                continue
            if line == "owns:":
                keys.append("owns")
                fields["owns"] = ""
                continue
            key, sep, value = line.partition(": ")
            if not sep:
                self.problems.append(f"{cid}: header line is not `key: value`: {line!r}")
                return None
            keys.append(key)
            fields[key] = value
        if keys != HEADER_KEYS:
            self.problems.append(f"{cid}: header keys are {keys}, expected {HEADER_KEYS}")
            return None
        fields["owns"] = owns
        for key in ("depends", "contracts"):
            fields[key] = [] if fields[key] == "-" else [v.strip() for v in fields[key].split(",")]
        self._check_values(cid, fields)
        return fields

    def _check_values(self, cid: str, h: dict) -> None:
        if h["id"] != cid:
            self.problems.append(f"{cid}: the header says id {h['id']}")
        if not STATUS.match(h["status"]):
            self.problems.append(f"{cid}: bad status {h['status']!r}")
        if h["model"] not in ("Sonnet", "Haiku"):
            self.problems.append(f"{cid}: bad model {h['model']!r}")
        sizes = ("L",) if cid.startswith("T0.") else ("S", "M")
        if h["size"] not in sizes:
            self.problems.append(f"{cid}: bad size {h['size']!r}")
        if not h["owns"]:
            self.problems.append(f"{cid}: owns nothing")
        if any(" " in p or "{" in p for p in h["owns"]):
            self.problems.append(f"{cid}: an owns path has a space or a brace")

    def _read_waves(self) -> list[tuple[str, str, list[str], list[str]]]:
        """(wave, opens-when, Tier 0 beside it, cards) for each row of the table."""
        waves = []
        for row in self._section(6):
            if not row.startswith("| **"):
                continue
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", row)[1:-1]]
            if len(cells) != 5:
                self.table_problems.append(f"wave table row has {len(cells)} cells: {row[:50]}")
                continue
            beside = [b.strip() for b in cells[2].split(",") if b.strip() and b.strip() != "-"]
            cards = [c.strip() for c in cells[3].split(",") if c.strip() and c.strip() != "-"]
            if not cells[4].isdigit() or int(cells[4]) != len(cards):
                self.table_problems.append(
                    f"wave {cells[0].strip('*')}: count {cells[4]} but {len(cards)} cards listed")
            waves.append((cells[0].strip("*"), cells[1], beside, cards))
        return waves

    # ---- derived -------------------------------------------------------
    @property
    def cards(self) -> dict[str, dict]:
        return {k: v for k, v in self.headers.items() if not k.startswith("T0.")}

    def opening_item(self, wave: str) -> str | None:
        opens = {w: o for w, o, *_ in self.waves}[wave]
        m = re.match(r"(T0\.\d+B?) merged", opens)
        return m.group(1) if m else None

    def tier0_before(self, wave: str) -> int:
        """Index of the last Tier 0 item certainly merged when the wave opens."""
        best = -1
        for w in self.order[: self.order.index(wave) + 1]:
            item = self.opening_item(w)
            if item in TIER0_IDS:
                best = TIER0_IDS.index(item)
        if "4" in self.order and self.order.index(wave) > self.order.index("4"):
            best = len(TIER0_IDS) - 1
        return best


# ---- owns overlap ------------------------------------------------------
def _base(path: str) -> str:
    path = path.split("#")[0]
    cut = min([path.find(c) for c in "*?[" if c in path] or [len(path)])
    return path[:cut]


def overlap(a: str, b: str) -> bool:
    """Two owns entries overlap: same file and section, or one path inside the other."""
    pa, _, sa = a.partition("#")
    pb, _, sb = b.partition("#")
    if sa and sb and sa != sb and pa == pb:
        return False
    if pa == pb:
        return True
    if fnmatch.fnmatch(pa, pb) or fnmatch.fnmatch(pb, pa):
        return True
    ba, bb = _base(pa), _base(pb)
    if ba != pa and pb.startswith(ba):
        return True
    if bb != pb and pa.startswith(bb):
        return True
    return pa.endswith("/") and pb.startswith(pa) or pb.endswith("/") and pa.startswith(pb)


def owns_overlap(plan: Plan, x: str, y: str) -> list[tuple[str, str]]:
    hx, hy = plan.headers[x]["owns"], plan.headers[y]["owns"]
    ox, oy = [p for p in hx if not p.startswith("!")], [p for p in hy if not p.startswith("!")]
    ex, ey = [p[1:] for p in hx if p.startswith("!")], [p[1:] for p in hy if p.startswith("!")]
    hits = []
    for a in ox:
        for b in oy:
            excluded = any(b.startswith(_base(e)) for e in ex) or any(a.startswith(_base(e)) for e in ey)
            if overlap(a, b) and not excluded:
                hits.append((a, b))
    return hits


# ---- the rules ----------------------------------------------------------
def check(text: str) -> list[str]:
    plan = Plan(text)
    out = list(plan.problems)
    h = plan.headers
    for cid in TIER0_IDS:
        if cid not in h:
            out.append(f"{cid}: no header")
    for cid, hd in h.items():
        out += [f"{cid}: depends on {d}, which is not defined" for d in hd["depends"] if d not in h]
        out += [f"{cid}: names contract {c}, which is not defined" for c in hd["contracts"]
                if c not in plan.contracts]
        if cid.startswith("T0."):
            want = "post1" if hd["status"] == "POST-1.0" else "T0"
            if hd["wave"] != want:
                out.append(f"{cid}: wave is {hd['wave']}, expected {want}")
        elif hd["wave"] not in plan.order:
            out.append(f"{cid}: wave {hd['wave']} is not in the wave table")
        elif (hd["status"] == "POST-1.0") != hd["wave"].startswith("post"):
            out.append(f"{cid}: status {hd['status']} and wave {hd['wave']} disagree about post-1.0")
    if out:
        return out
    out += _dependencies(plan)
    out += _paths(plan)
    out += _table(plan)
    return out + plan.table_problems


def _dependencies(plan: Plan) -> list[str]:
    out = []
    cards = plan.cards
    for cid, hd in cards.items():
        if hd["wave"] not in plan.order:
            continue
        mine = plan.order.index(hd["wave"])
        for dep in hd["depends"]:
            if dep.startswith("T0."):
                if TIER0_IDS.index(dep) > plan.tier0_before(hd["wave"]):
                    out.append(f"{cid}: depends on {dep}, not merged when wave {hd['wave']} opens")
            elif cards[dep]["wave"] not in plan.order or plan.order.index(cards[dep]["wave"]) >= mine:
                out.append(f"{cid}: depends on {dep}, which is in wave {cards[dep]['wave']}, "
                           f"not before wave {hd['wave']}")
    for n, item in enumerate(TIER0_IDS):
        for dep in plan.headers[item]["depends"]:
            if dep.startswith("T0."):
                if TIER0_IDS.index(dep) >= n:
                    out.append(f"{item}: depends on {dep}, which does not come before it")
            elif cards[dep]["wave"] in plan.order and plan.tier0_before(cards[dep]["wave"]) >= n:
                out.append(f"{item}: depends on {dep}, which cannot be done before it")
    return out


def _paths(plan: Plan) -> list[str]:
    out = []
    for wave, _, beside, members in plan.waves:
        ids = sorted(c for c, hd in plan.cards.items() if hd["wave"] == wave)
        for i, x in enumerate(ids):
            for y in ids[i + 1:]:
                hits = owns_overlap(plan, x, y)
                if hits:
                    out.append(f"wave {wave}: {x} and {y} both own {hits[0][0]} / {hits[0][1]}")
        for cid in ids:
            for item in beside:
                if item not in plan.headers:
                    out.append(f"wave {wave}: Tier 0 item {item} beside it is not defined")
                    continue
                hits = owns_overlap(plan, cid, item)
                if hits:
                    out.append(f"wave {wave}: {cid} owns {hits[0][0]}, which {item} beside it owns "
                               f"({hits[0][1]})")
        del members
    return out


def _table(plan: Plan) -> list[str]:
    out = []
    listed: dict[str, str] = {}
    for wave, _, _, members in plan.waves:
        for c in members:
            if c in listed:
                out.append(f"wave table: {c} is listed in waves {listed[c]} and {wave}")
            listed[c] = wave
    for cid, hd in plan.cards.items():
        if cid not in listed:
            out.append(f"wave table: {cid} (wave {hd['wave']}) is not listed")
        elif listed[cid] != hd["wave"]:
            out.append(f"wave table: {cid} is listed in wave {listed[cid]}, its header says {hd['wave']}")
    out += [f"wave table: {c} is not a card" for c in listed if c not in plan.cards]
    return out


# ---- --next ---------------------------------------------------------------
def _done(plan: Plan, cid: str) -> bool:
    return cid in plan.headers and plan.headers[cid]["status"].startswith("DONE")


def _holds_open(plan: Plan, cid: str) -> bool:
    status = plan.headers[cid]["status"]
    return not (status.startswith(("DONE", "BLOCKED")) or status == "POST-1.0")


def next_cards(text: str) -> list[str]:
    plan = Plan(text)
    out = []
    for wave, _, _, members in plan.waves:
        n = plan.order.index(wave)
        item = plan.opening_item(wave)
        if item and not _done(plan, item):
            continue
        earlier = [c for w, _, _, ms in plan.waves[:n] for c in ms if c in plan.headers]
        if any(_holds_open(plan, c) for c in earlier):
            continue
        for c in members:
            hd = plan.headers.get(c)
            if hd and hd["status"] == "OPEN" and all(_done(plan, d) for d in hd["depends"]):
                out.append(f"{c} (wave {wave})")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--roadmap", type=Path, default=ROADMAP)
    parser.add_argument("--next", action="store_true", help="list the cards that can start now")
    args = parser.parse_args(argv)
    text = args.roadmap.read_text()
    if args.next:
        problems = check(text)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print("\n".join(next_cards(text)))
        return 0
    problems = check(text)
    for p in problems:
        print(p)
    if problems:
        print(f"plan_check: {len(problems)} violation(s)", file=sys.stderr)
        return 1
    print("plan_check: the plan obeys its rules")
    return 0


if __name__ == "__main__":
    sys.exit(main())
