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
the content is right, only that the skeleton survived and that every id
the text cites exists:

  * docs/roadmap.md: the eight numbered sections, in order and by title;
    section 3's subsections 3.1-3.6; Tier 0 items T0.1, T0.1B, T0.2-T0.15
    each once and in order, in the summary table, each with a contract;
    the card workstreams and card ids (unique, each naming what it owns);
    the design rules DR1-DR7, the invariants I1-I8, the checklist rows
    P1-P13; the owner questions (four columns, a default, all cited ones
    defined);
  * docs/decisions.md: B1-B20, D1-D23 and N1-N45, each defined once with
    five columns, and every decision id the roadmap cites defined there;
  * the one-planning-file rule: the documents name docs/roadmap.md and the
    old root ROADMAP.md and BLOCKING.md are gone.
"""

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
CARD_PREFIXES = "MEAS|SEC|API|ADM|OPS|INS|DOC|CI|QA|REF|ADD"
CARD = re.compile(rf"^\*\*((?:{CARD_PREFIXES})-[A-Z0-9-]+) · ", re.M)
WORKSTREAMS = ["MEAS", "SEC", "API", "ADM", "CLI", "OPS", "INS", "DOC", "CI", "QA", "REF", "ADD"]
TIER0_IDS = ["T0.1", "T0.1B"] + [f"T0.{n}" for n in range(2, 16)]


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
            (1, "Design philosophy"),
            (2, "Goal, checklist and invariants"),
            (3, "Layout"),
            (4, "Tier 0"),
            (5, "Task cards"),
            (6, "Blocked on the owner"),
            (7, "Sequencing"),
            (8, "How a worker uses this file"),
        ],
    )
    def test_each_section_is_the_one_it_should_be(self, number, word):
        """Numbers alone would pass a file whose sections were shuffled."""
        title = dict(_sections())[number]
        assert word in title, (number, title)

    def test_the_subsections_exist(self):
        found = {m.group(1) for m in map(SUBSECTION.match, LINES) if m}
        expected = {f"3.{n}" for n in range(1, 7)}
        expected |= {f"5.{n}" for n in range(1, 15)}
        expected |= {"7.1", "7.2"}
        assert expected <= found, sorted(expected - found)

    def test_the_layout_section_lists_the_docs_tree(self):
        """Section 3.1 is the target layout this repository follows."""
        text = _section_text(3)
        for path in ("roadmap.md", "decisions.md", "principles.md", "install.md",
                     "security/architecture.md", "ui/development.md", "archive/planning-history.md"):
            assert path in text, path


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


class TestTierZero:
    def test_the_items_are_present_once_and_in_order(self):
        """T0.1, T0.1B, then T0.2 to T0.15."""
        ids = [m.group(1) for m in map(TIER0.match, LINES) if m]
        assert ids == TIER0_IDS, ids

    def test_every_item_ends_in_a_contract(self):
        """The contract is what makes the cards that follow possible: the
        module names, signatures, locations and registries they build on."""
        text = _section_text(4)
        parts = re.split(r"^### T0\.\d+B? ", text, flags=re.M)[1:]
        assert len(parts) == len(TIER0_IDS)
        missing = [i for i, body in zip(TIER0_IDS, parts, strict=True) if "contract" not in body.lower()]
        assert missing == [], f"Tier 0 items with no contract: {missing}"

    def test_the_summary_table_lists_every_item(self):
        text = _section_text(4)
        for item in TIER0_IDS:
            assert re.search(rf"^\| {re.escape(item)} \|", text, re.M), item

    def test_every_cited_tier_zero_id_exists(self):
        cited = set(re.findall(r"\bT0\.\d+B?\b", TEXT))
        assert cited <= set(TIER0_IDS), sorted(cited - set(TIER0_IDS))


class TestTheCards:
    def test_card_ids_are_unique(self):
        ids = CARD.findall(TEXT)
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        assert dupes == [], dupes

    def test_every_workstream_has_cards(self):
        """CLI cards are rows of the section 5.7 table, the rest are headed
        blocks; both count."""
        headed = {i.split("-")[0] for i in CARD.findall(TEXT)}
        in_table = {m.group(1) for m in re.finditer(r"^\| (CLI)-[A-Z]+ \|", TEXT, re.M)}
        assert set(WORKSTREAMS) <= headed | in_table, sorted(set(WORKSTREAMS) - (headed | in_table))

    def test_every_headed_card_names_what_it_owns(self):
        """The line the swarm brief depends on: a worker touches only the
        files its card owns. A MEAS card owns only its tools/measure script and
        may instead say what it gates or depends on."""
        text = _section_text(5)
        blocks = re.split(rf"^(?=\*\*(?:{CARD_PREFIXES})-[A-Z0-9-]+ · )", text, flags=re.M)[1:]
        assert len(blocks) >= 100, len(blocks)
        bad = []
        for block in blocks:
            card = block.split(" · ")[0].strip("*")
            needed = ("Owns", "Gates", "Depends") if card.startswith("MEAS") else ("Owns",)
            if not any(word in block for word in needed):
                bad.append(card)
        assert bad == [], f"cards that do not say what they own or depend on: {bad}"


class TestDecisions:
    def test_the_groups_are_each_present_once_with_five_columns(self):
        """B1-B20, D1-D23, N1-N45: id, date, decision, reason, consequences.
        A stray pipe in prose splits a row silently."""
        expected = [f"B{n}" for n in range(1, 21)] + [f"D{n}" for n in range(1, 24)] + [f"N{n}" for n in range(1, 46)]
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
        rows = [line for line in _section_text(6).splitlines() if line.startswith("| **Q-")]
        assert rows
        for row in rows:
            cells = _cells(row)
            assert len(cells) == 4, row[:60]
            assert all(c.strip() for c in cells), row[:60]

    def test_every_cited_question_is_defined_in_section_6(self):
        defined = set(re.findall(r"^\| \*\*(Q-[A-Z0-9]+)\*\*", _section_text(6), re.M))
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
        for word in ("Tier 0", "task cards", "blocked on", "waves"):
            assert word in text, word
