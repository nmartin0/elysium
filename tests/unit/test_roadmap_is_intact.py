"""
docs/roadmap.md and docs/decisions.md keep their shape.

WHY THIS EXISTS, and it is not hypothetical. Patch 493 inserted two rows
into a table in the planning file and in doing so DELETED the heading of
its most important item. Seven patches shipped after that with the
heading gone and nothing noticed: not the linter, which does not read
Markdown, and not the author, who checked line lengths and reference
counts and never once checked that the document still had its sections.

The roadmap is edited by a strong model and by many parallel workers (one
card each), so the same failure is likely. This test cannot judge whether
the content is right, only that the skeleton survived, that every id the
text cites exists, and that the parallel plan obeys its own rules:

  * docs/roadmap.md: the eight numbered sections, in order and by title,
    with their subsections; Tier 0 items T0.1, T0.1B, T0.2-T0.6, T0.6B,
    T0.7-T0.15 each once and in order, in the summary table, each naming its
    contracts; every contract of section 3 defined once with its anchor;
    the design rules DR1-DR7, the invariants I1-I8, the checklist rows
    P1-P13; the owner questions (four columns, a default, all cited ones
    defined);
  * every card and Tier 0 item has a header block in the fixed format of
    section 1.2; ids are unique; every cited card, Tier 0 and contract id
    exists; the wave rules of section 6.1 hold (no dependency in the same or
    a later wave, no two cards of one wave owning one path, no card owning a
    path of the Tier 0 item beside its wave); the wave table matches the
    headers;
  * docs/decisions.md: B1-B20, D1-D23 and N1-N91, each defined once with
    five columns, and every decision id the roadmap cites defined there;
  * the one-planning-file rule: the documents name docs/roadmap.md and the
    old root ROADMAP.md and BLOCKING.md are gone.

tools/plan_check.py (T0.1 step 7) will carry the same rules as a script;
until it exists, the wave and ownership checks live here.
"""

import fnmatch
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "docs/roadmap.md").read_text()
DECISIONS = (ROOT / "docs/decisions.md").read_text()
LINES = TEXT.splitlines()

SECTION = re.compile(r"^## (\d+)\. (.*)$")
SUBSECTION = re.compile(r"^### (\d+\.\d+) (.*)$")
TIER0 = re.compile(r"^### (T0\.\d+B?) (.*)$")
PREFIXES = "MEAS|SEC|API|ADM|CLI|OPS|INS|DOC|CI|QA|REF|ADD|APP"
CARD_ID = rf"(?:{PREFIXES})-[A-Za-z0-9-]*[A-Za-z0-9]"
CARD_HEADING = re.compile(rf"^#### ({CARD_ID}) · (.+)$")
CONTRACT_HEADING = re.compile(r"^### (C-[A-Z-]*[A-Z]) · (.+)$")
WORKSTREAMS = ["MEAS", "SEC", "API", "ADM", "CLI", "OPS", "INS", "DOC", "CI", "QA", "REF", "ADD", "APP"]
TIER0_IDS = ["T0.1", "T0.1B"] + [f"T0.{n}" for n in range(2, 7)] + ["T0.6B"] + [f"T0.{n}" for n in range(7, 16)]
HEADER_KEYS = ["id", "wave", "status", "size", "model", "depends", "contracts", "owns"]
STATUS = re.compile(r"^(OPEN|IN PROGRESS|DONE [0-9a-f]{7,40}|BLOCKED Q-[A-Z0-9]+|POST-1\.0)$")


def _sections():
    return [(int(m.group(1)), m.group(2)) for m in (SECTION.match(line) for line in LINES) if m]


def _section_text(number):
    """The text of `## number.` up to the next `## ` heading."""
    start = next(n for n, line in enumerate(LINES) if line.startswith(f"## {number}. "))
    end = next((n for n in range(start + 1, len(LINES)) if LINES[n].startswith("## ")), len(LINES))
    return "\n".join(LINES[start:end])


def _cells(row):
    return re.split(r"(?<!\\)\|", row)[1:-1]


def _decision_ids():
    return re.findall(r"^\| ([BDN]\d+) \|", DECISIONS, re.M)


def _headers():
    """Every header block: a ```card fence right after a card or Tier 0 heading
    and one blank line. Returns {id: (heading id, list of raw lines)}."""
    found = {}
    for n, line in enumerate(LINES):
        m = CARD_HEADING.match(line) or TIER0.match(line)
        if not m:
            continue
        assert LINES[n + 1] == "" and LINES[n + 2] == "```card", f"no header block after: {line}"
        end = next(k for k in range(n + 3, len(LINES)) if LINES[k] == "```")
        assert m.group(1) not in found, f"defined twice: {m.group(1)}"
        found[m.group(1)] = LINES[n + 3:end]
    return found


def _parse(raw):
    """The fixed format of section 1.2, strictly."""
    fields, owns, keys = {}, [], []
    for line in raw:
        if line.startswith("  - "):
            assert keys and keys[-1] == "owns", line
            owns.append(line[4:])
            continue
        key, sep, value = line.partition(": ")
        if line == "owns:":
            key, value = "owns", ""
        else:
            assert sep, f"not `key: value`: {line!r}"
        keys.append(key)
        fields[key] = value
    assert keys == HEADER_KEYS, keys
    fields["owns"] = owns
    for key in ("depends", "contracts"):
        fields[key] = [] if fields[key] == "-" else [v.strip() for v in fields[key].split(",")]
    return fields


HEADERS = {k: _parse(v) for k, v in _headers().items()}
CARDS = {k: v for k, v in HEADERS.items() if not k.startswith("T0.")}


def _wave_rows():
    rows = [r for r in _section_text(6).splitlines() if r.startswith("| **")]
    out = []
    for row in rows:
        cells = [c.strip() for c in _cells(row)]
        depends = [c.strip() for c in cells[3].split(",") if c.strip()]
        out.append((cells[0].strip("*"), cells[1], cells[2], depends, cells[4]))
    return out


WAVES = _wave_rows()
WAVE_ORDER = [w for w, *_ in WAVES]


def _opening_item(wave):
    """The Tier 0 item merged before the wave opens, or None (inherits)."""
    opens = dict((w, o) for w, o, *_ in WAVES)[wave]
    m = re.match(r"(T0\.\d+B?) merged", opens)
    return m.group(1) if m else None


def _tier0_before(wave):
    """Index of the last Tier 0 item certainly merged when the wave opens."""
    best = -1
    for w in WAVE_ORDER[: WAVE_ORDER.index(wave) + 1]:
        item = _opening_item(w)
        if item:
            best = TIER0_IDS.index(item)
    if WAVE_ORDER.index(wave) > WAVE_ORDER.index("4"):
        best = len(TIER0_IDS) - 1
    return best


def _base(path):
    path = path.split("#")[0]
    cut = min([path.find(c) for c in "*?[" if c in path] or [len(path)])
    return path[:cut]


def _overlap(a, b):
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
    globbed_a, globbed_b = ba != pa, bb != pb
    if globbed_a and pb.startswith(ba):
        return True
    if globbed_b and pa.startswith(bb):
        return True
    return pa.endswith("/") and pb.startswith(pa) or pb.endswith("/") and pa.startswith(pb)


def _owns_overlap(x, y):
    ox = [p for p in HEADERS[x]["owns"] if not p.startswith("!")]
    oy = [p for p in HEADERS[y]["owns"] if not p.startswith("!")]
    ex = [p[1:] for p in HEADERS[x]["owns"] if p.startswith("!")]
    ey = [p[1:] for p in HEADERS[y]["owns"] if p.startswith("!")]
    hits = []
    for a in ox:
        for b in oy:
            excluded = any(b.startswith(_base(e)) for e in ex) or any(a.startswith(_base(e)) for e in ey)
            if _overlap(a, b) and not excluded:
                hits.append((a, b))
    return hits


class TestTheSkeletonExists:
    def test_the_title_is_the_first_line(self):
        """Losing it silently makes the file anonymous."""
        assert LINES[0] == "# Elysium roadmap"

    def test_the_eight_sections_are_present_once_and_in_order(self):
        """A gap or a repeat means an insertion overwrote a heading."""
        numbers = [n for n, _ in _sections()]
        assert numbers == list(range(1, 9)), numbers

    @pytest.mark.parametrize(
        "number,word",
        [
            (1, "how to take a card"),
            (2, "Design rules, checklist and invariants"),
            (3, "Contracts"),
            (4, "Tier 0"),
            (5, "Task cards"),
            (6, "Waves"),
            (7, "Blocked on the owner"),
            (8, "History"),
        ],
    )
    def test_each_section_is_the_one_it_should_be(self, number, word):
        """Numbers alone would pass a file whose sections were shuffled."""
        title = dict(_sections())[number]
        assert word in title, (number, title)

    def test_the_subsections_exist(self):
        found = {m.group(1) for m in map(SUBSECTION.match, LINES) if m}
        expected = {f"1.{n}" for n in range(1, 6)} | {f"2.{n}" for n in range(1, 5)}
        expected |= {f"5.{n}" for n in range(1, 14)} | {f"6.{n}" for n in range(1, 5)}
        expected |= {f"8.{n}" for n in range(1, 4)}
        assert expected <= found, sorted(expected - found)

    def test_the_repository_contract_lists_the_docs_tree(self):
        """C-REPO is the target layout this repository follows."""
        start = TEXT.index("### C-REPO ")
        text = TEXT[start:TEXT.index("\n### ", start + 1)]
        for path in ("roadmap.md", "decisions.md", "principles.md", "install.md", "security/architecture.md",
                     "ui/development.md", "archive/planning-history.md", "scripts/", "site/"):
            assert path in text, path

    def test_the_brief_is_in_section_one_and_names_the_worktree(self):
        """The worker reads section 1 and nothing else; it must say where to work."""
        text = _section_text(1)
        for phrase in ("../elysium-wt/<ID>", "card/<ID>", "Card: <ID>", "REPORT", "GATES", "tools/heavy.sh"):
            assert phrase in text, phrase


class TestDesignRulesInvariantsAndChecklist:
    def test_dr1_to_dr7_are_each_defined_once(self):
        for n in range(1, 8):
            assert len(re.findall(rf"^\*\*DR{n}\. ", TEXT, re.M)) == 1, n

    def test_every_cited_design_rule_exists(self):
        cited = {int(n) for n in re.findall(r"\bDR(\d+)\b", TEXT)}
        assert cited <= set(range(1, 8)), sorted(cited)

    def test_i1_to_i8_are_each_a_row_of_the_invariant_table(self):
        for n in range(1, 9):
            assert len(re.findall(rf"^\| I{n} \|", TEXT, re.M)) == 1, n

    def test_p1_to_p13_are_each_a_row_of_the_production_ready_table(self):
        for n in range(1, 14):
            assert len(re.findall(rf"^\| P{n} \|", TEXT, re.M)) == 1, n


class TestContracts:
    def test_each_contract_is_defined_once_with_its_anchor(self):
        ids = [m.group(1) for m in map(CONTRACT_HEADING.match, LINES) if m]
        assert len(ids) == len(set(ids)) and len(ids) >= 30, ids
        for cid in ids:
            assert f'<a id="{cid.lower()}"></a>' in TEXT, cid

    def test_every_cited_contract_exists(self):
        defined = {m.group(1) for m in map(CONTRACT_HEADING.match, LINES) if m}
        cited = set(re.findall(r"\bC-[A-Z]+(?:-[A-Z]+)*\b", TEXT))
        assert cited <= defined, sorted(cited - defined)


class TestTierZero:
    def test_the_items_are_present_once_and_in_order(self):
        """T0.1, T0.1B, T0.2 to T0.6, T0.6B, then T0.7 to T0.15."""
        ids = [m.group(1) for m in map(TIER0.match, LINES) if m]
        assert ids == TIER0_IDS, ids

    def test_every_item_names_its_contracts(self):
        """The contracts are what makes the cards that follow possible."""
        text = _section_text(4)
        parts = re.split(r"^### T0\.\d+B? ", text, flags=re.M)[1:]
        assert len(parts) == len(TIER0_IDS)
        missing = [i for i, body in zip(TIER0_IDS, parts, strict=True)
                   if "- **Contract.** [C-" not in body or not HEADERS[i]["contracts"]]
        assert missing == [], f"Tier 0 items with no contract: {missing}"

    def test_every_item_has_numbered_steps(self):
        text = _section_text(4)
        parts = re.split(r"^### T0\.\d+B? ", text, flags=re.M)[1:]
        missing = [i for i, body in zip(TIER0_IDS, parts, strict=True)
                   if not re.search(r"^  1[a-z]?\. ", body, re.M) and not re.search(r"\(1\) ", body)]
        assert missing == [], f"Tier 0 items without numbered steps: {missing}"

    def test_the_summary_table_lists_every_item(self):
        text = _section_text(4)
        for item in TIER0_IDS:
            assert re.search(rf"^\| {re.escape(item)} \|", text, re.M), item

    def test_every_cited_tier_zero_id_exists(self):
        cited = set(re.findall(r"\bT0\.\d+B?\b", TEXT))
        assert cited <= set(TIER0_IDS), sorted(cited - set(TIER0_IDS))

    def test_tier_zero_is_strictly_sequential(self):
        """A Tier 0 item depends only on earlier Tier 0 items (and cards)."""
        for n, item in enumerate(TIER0_IDS):
            h = HEADERS[item]
            # T0.9 (lake encryption) is post-1.0 (N73): it keeps its place in the order
            assert h["wave"] == ("post1" if h["status"] == "POST-1.0" else "T0"), item
            for dep in h["depends"]:
                if dep.startswith("T0."):
                    assert TIER0_IDS.index(dep) < n, (item, dep)


class TestTheHeaders:
    def test_every_card_and_item_has_a_header_in_the_fixed_format(self):
        assert set(TIER0_IDS) <= set(HEADERS)
        assert len(CARDS) >= 140, len(CARDS)
        for cid, h in HEADERS.items():
            assert h["id"] == cid, cid
            assert STATUS.match(h["status"]), (cid, h["status"])
            assert h["model"] in ("Sonnet", "Haiku"), cid
            assert h["size"] in (("L",) if cid.startswith("T0.") else ("S", "M")), (cid, h["size"])
            assert h["owns"], f"{cid} owns nothing"
            assert all(" " not in p and "{" not in p for p in h["owns"]), cid

    def test_every_workstream_has_cards(self):
        assert {c.split("-")[0] for c in CARDS} == set(WORKSTREAMS)

    def test_every_cited_card_id_exists(self):
        defined = set(CARDS)
        history = TEXT.index("\n## 8. ")  # section 8 names merged and deleted cards on purpose
        cited = set(re.findall(rf"(?<![\w/.-])({CARD_ID})(?![\w-])", TEXT[:history]))
        allowed = {"REF-RENAME"}  # becomes a card only when Q-NAME is answered (section 7)
        findings = re.compile(r"SEC-\d+")  # rows of docs/security/findings.csv, not cards
        unknown = sorted(c for c in cited - defined - allowed if not findings.fullmatch(c))
        assert unknown == [], unknown

    def test_every_dependency_and_contract_is_defined(self):
        contracts = {m.group(1) for m in map(CONTRACT_HEADING.match, LINES) if m}
        for cid, h in HEADERS.items():
            for dep in h["depends"]:
                assert dep in HEADERS, (cid, dep)
            for con in h["contracts"]:
                assert con in contracts, (cid, con)


class TestTheWaves:
    def test_the_wave_table_matches_the_headers(self):
        listed = {c: w for w, _, _, cards, _ in WAVES for c in cards}
        assert listed == {c: h["wave"] for c, h in CARDS.items()}
        for w, _, _, cards, count in WAVES:
            assert int(count) == len(cards), w

    def test_no_card_depends_on_its_own_or_a_later_wave(self):
        bad = []
        for cid, h in CARDS.items():
            mine = WAVE_ORDER.index(h["wave"])
            for dep in h["depends"]:
                if dep.startswith("T0."):
                    if TIER0_IDS.index(dep) > _tier0_before(h["wave"]):
                        bad.append((cid, dep))
                elif WAVE_ORDER.index(CARDS[dep]["wave"]) >= mine:
                    bad.append((cid, dep))
        assert bad == [], bad

    def test_a_tier_zero_item_depends_only_on_cards_that_can_be_done_before_it(self):
        bad = []
        for n, item in enumerate(TIER0_IDS):
            for dep in HEADERS[item]["depends"]:
                if not dep.startswith("T0.") and _tier0_before(CARDS[dep]["wave"]) >= n:
                    bad.append((item, dep))
        assert bad == [], bad

    def test_no_two_cards_in_a_wave_own_the_same_path(self):
        bad = []
        for w, *_ in WAVES:
            ids = sorted(c for c, h in CARDS.items() if h["wave"] == w)
            for i, x in enumerate(ids):
                for y in ids[i + 1:]:
                    hits = _owns_overlap(x, y)
                    if hits:
                        bad.append((w, x, y, hits[0]))
        assert bad == [], bad

    def test_post_1_0_cards_are_exactly_the_cards_in_the_post_waves(self):
        """Moved out of 1.0 (N73, N78): status and wave say the same thing."""
        bad = [c for c, h in HEADERS.items() if h["status"] == "POST-1.0" and not h["wave"].startswith("post")]
        bad += [c for c, h in HEADERS.items() if h["wave"].startswith("post") and h["status"] != "POST-1.0"]
        assert bad == [], bad

    def test_no_card_owns_a_path_of_the_tier_zero_item_beside_its_wave(self):
        bad = []
        for w, _, beside, *_ in WAVES:
            items = [b.strip() for b in beside.split(",") if b.strip() and b.strip() != "-"]
            for cid in (c for c, h in CARDS.items() if h["wave"] == w):
                for item in items:
                    hits = _owns_overlap(cid, item)
                    if hits:
                        bad.append((w, cid, item, hits[0]))
        assert bad == [], bad


class TestDecisions:
    def test_the_groups_are_each_present_once_with_five_columns(self):
        """B1-B20, D1-D23, N1-N91: id, date, decision, reason, consequences.
        A stray pipe in prose splits a row silently."""
        expected = [f"B{n}" for n in range(1, 21)] + [f"D{n}" for n in range(1, 24)] + [f"N{n}" for n in range(1, 92)]
        assert sorted(_decision_ids()) == sorted(expected)
        for row in re.findall(r"^\| [BDN]\d+ \|.*$", DECISIONS, re.M):
            assert len(_cells(row)) == 5, row[:60]

    def test_every_decision_the_roadmap_cites_is_defined(self):
        defined = set(_decision_ids())
        cited = set(re.findall(r"(?<![-A-Z/`\w])([BDN]\d{1,2})\b", TEXT)) - {"D00"}
        assert cited <= defined, sorted(cited - defined)

    def test_n1_to_n21_are_marked_accepted_by_the_owner(self):
        """The owner accepted N1-N21 on 3 November 2026; the heading says so."""
        assert "## N1-N21. Production roadmap decisions (owner, 3 November 2026: all accepted)" in DECISIONS


class TestBlockedOnAPerson:
    def test_every_question_has_the_columns_and_a_default(self):
        rows = [line for line in _section_text(7).splitlines() if line.startswith("| **Q-")]
        assert rows
        for row in rows:
            cells = _cells(row)
            assert len(cells) == 4, row[:60]
            assert all(c.strip() for c in cells), row[:60]

    def test_every_cited_question_is_defined_in_section_7(self):
        defined = set(re.findall(r"^\| \*\*(Q-[A-Z0-9]+)\*\*", _section_text(7), re.M))
        cited = set(re.findall(r"\bQ-[A-Z][A-Z0-9]+\b", TEXT))
        assert cited <= defined, sorted(cited - defined)


class TestOneFile:
    def test_the_old_planning_files_are_gone(self):
        assert not (ROOT / "BLOCKING.md").exists()
        assert not (ROOT / "ROADMAP.md").exists()

    @pytest.mark.parametrize("doc", ["CLAUDE.md", "AGENTS.md", "docs/principles.md", "docs/rules.md", "README.md"])
    def test_the_rules_documents_name_the_one_planning_file(self, doc):
        text = (ROOT / doc).read_text()
        assert "docs/roadmap.md" in text, doc
        assert "BLOCKING.md" not in text, doc

    def test_claude_md_describes_how_the_roadmap_is_organised(self):
        text = (ROOT / "CLAUDE.md").read_text()
        for word in ("Tier 0", "task cards", "blocked on", "waves", "contracts", "seventeen"):
            assert word in text, word

    @pytest.mark.parametrize("doc", ["CLAUDE.md", "AGENTS.md"])
    def test_the_agent_guides_point_swarm_workers_at_the_brief(self, doc):
        """They must not contradict the brief a parallel worker follows."""
        assert "Working as a swarm worker" in (ROOT / doc).read_text(), doc
