"""
ROADMAP.md keeps its shape.

WHY THIS EXISTS, and it is not hypothetical. Patch 493 inserted two rows
into a table in the planning file and in doing so DELETED the heading of
its most important item. Seven patches shipped after that with the
heading gone and nothing noticed: not the linter, which does not read
Markdown, and not the author, who checked line lengths and reference
counts and never once checked that the document still had its sections.

This file is now the one planning file, edited by a strong model and by
many parallel workers (one card each), so the same failure is likelier,
not less likely. It cannot judge whether the content is right, only that
the skeleton survived and that every id the text cites exists:

  * the eight numbered sections, in order;
  * the fifteen Tier 0 items T0.1-T0.15, each once and in order;
  * the card workstreams of section 4;
  * decisions D1-D23 and N1-N21, each once, N1-N21 marked DECIDED;
  * the questions of section 5, and every Q-id cited anywhere defined there;
  * section 8's subsections, which carry the older plan word for word;
  * the one-planning-file rule: BLOCKING.md is gone and the docs say so.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "ROADMAP.md").read_text()
LINES = TEXT.splitlines()

SECTION = re.compile(r"^## (\d+)\. (.*)$")
SUBSECTION = re.compile(r"^### (\d+\.\d+) (.*)$")
TIER0 = re.compile(r"^### T0\.(\d+) (.*)$")
CARD = re.compile(r"^\*\*((?:MEAS|SEC|API|ADM|OPS|INS|DOC|CI|REF|ADD)-[A-Z0-9-]+) · ", re.M)
WORKSTREAMS = ["MEAS", "SEC", "API", "ADM", "CLI", "OPS", "INS", "DOC", "CI", "REF", "ADD"]


def _sections():
    return [(int(m.group(1)), m.group(2)) for m in (SECTION.match(line) for line in LINES) if m]


def _section_text(number):
    """The text of `## number.` up to the next `## ` heading."""
    start = next(n for n, line in enumerate(LINES) if line.startswith(f"## {number}. "))
    end = next((n for n in range(start + 1, len(LINES)) if LINES[n].startswith("## ")), len(LINES))
    return "\n".join(LINES[start:end])


class TestTheSkeletonExists:
    def test_the_title_is_the_first_line(self):
        """Losing it silently makes the file anonymous."""
        assert LINES[0] == "# Elysium production roadmap"

    def test_the_eight_sections_are_present_once_and_in_order(self):
        """A gap or a repeat means an insertion overwrote a heading."""
        numbers = [n for n, _ in _sections()]
        assert numbers == list(range(1, 9)), numbers

    def test_no_section_heading_is_empty(self):
        for number, title in _sections():
            assert title.strip(), number

    @pytest.mark.parametrize(
        "number,word",
        [
            (1, "production ready"),
            (2, "Decisions"),
            (3, "Tier 0"),
            (4, "Tier 1+"),
            (5, "Blocked on a person"),
            (6, "Sequencing"),
            (7, "swarm worker"),
            (8, "refactor plan"),
        ],
    )
    def test_each_section_is_the_one_it_should_be(self, number, word):
        """Numbers alone would pass a file whose sections were shuffled."""
        title = dict(_sections())[number]
        assert word in title, (number, title)

    def test_the_subsections_of_the_big_sections_exist(self):
        found = {m.group(1) for m in map(SUBSECTION.match, LINES) if m}
        expected = {
            "2.1",
            "2.2",
            "2.3",
            "4.1",
            "4.2",
            "4.3",
            "4.4",
            "4.5",
            "4.6",
            "4.7",
            "4.8",
            "4.9",
            "4.10",
            "4.11",
            "4.12",
            "4.13",
            "6.1",
            "6.2",
            "6.3",
            "6.4",
        }
        assert expected <= found, sorted(expected - found)


class TestTierZero:
    def test_t0_1_to_t0_15_are_present_once_and_in_order(self):
        numbers = [int(m.group(1)) for m in map(TIER0.match, LINES) if m]
        assert numbers == list(range(1, 16)), numbers

    def test_every_item_ends_in_a_contract(self):
        """The contract is what makes the cards that follow possible: the
        module names, signatures, locations and registries they build on."""
        text = _section_text(3)
        parts = re.split(r"^### T0\.\d+ ", text, flags=re.M)[1:]
        assert len(parts) == 15
        missing = [n for n, body in enumerate(parts, 1) if "contract" not in body.lower()]
        assert missing == [], f"Tier 0 items with no contract: {missing}"

    def test_the_summary_table_lists_every_item(self):
        text = _section_text(3)
        for n in range(1, 16):
            assert re.search(rf"^\| T0\.{n} \|", text, re.M), n

    def test_every_cited_tier_zero_id_exists(self):
        cited = {int(n) for n in re.findall(r"\bT0\.(\d+)\b", TEXT)}
        assert cited <= set(range(1, 16)), sorted(cited - set(range(1, 16)))


class TestTheCards:
    def test_card_ids_are_unique(self):
        ids = CARD.findall(TEXT)
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        assert dupes == [], dupes

    def test_every_workstream_has_cards(self):
        """CLI cards are rows of the section 4.7 table, the rest are headed
        blocks; both count."""
        headed = {i.split("-")[0] for i in CARD.findall(TEXT)}
        in_table = {m.group(1) for m in re.finditer(r"^\| (CLI)-[A-Z]+ \|", TEXT, re.M)}
        assert set(WORKSTREAMS) <= headed | in_table, sorted(set(WORKSTREAMS) - (headed | in_table))

    def test_every_headed_card_names_the_files_it_owns(self):
        """The line the swarm brief depends on: a worker touches only the
        files its card owns. Long cards say "- Owns:", the compact ones
        "Owns ..." inline; a MEAS card owns nothing in src/ and instead
        says what it depends on or gates."""
        text = TEXT.split("\n## 5. ", 1)[0].split("\n## 4. ", 1)[1]
        blocks = re.split(
            r"^(?=\*\*(?:MEAS|SEC|API|ADM|OPS|INS|DOC|CI|REF|ADD)"
            r"-[A-Z0-9-]+ · )",
            text,
            flags=re.M,
        )[1:]
        assert len(blocks) >= 100, len(blocks)
        bad = []
        for block in blocks:
            card = block.split(" · ")[0].strip("*")
            needed = "Depends" if card.startswith("MEAS") else "Owns"
            if needed not in block:
                bad.append(card)
        assert bad == [], f"cards that do not say {needed!r}: {bad}"


class TestDecisions:
    def test_d1_to_d23_are_each_present_once(self):
        text = TEXT.split("### 2.2", 1)[0]
        for n in range(1, 24):
            assert len(re.findall(rf"^\| D{n} \|", text, re.M)) == 1, n

    def test_n1_to_n21_are_each_present_once_and_decided(self):
        """The owner accepted all of them on 3 November 2026. A row that
        loses the word is a decision that looks open again."""
        text = _section_text(2)
        for n in range(1, 22):
            rows = re.findall(rf"^\| \*\*N{n}\*\* \|.*$", text, re.M)
            assert len(rows) == 1, (n, len(rows))
            assert "DECIDED, owner, 3 November 2026" in rows[0], n

    def test_the_decision_table_rows_keep_their_columns(self):
        """Five cells per N row: id, decision, reason, recommendation,
        cost of reversal. A stray pipe in prose splits a row silently."""
        text = _section_text(2)
        for n in range(1, 22):
            row = re.search(rf"^\| \*\*N{n}\*\* \|.*$", text, re.M).group(0)
            cells = re.split(r"(?<!\\)\|", row)[1:-1]
            assert len(cells) == 5, (n, len(cells))


class TestBlockedOnAPerson:
    def test_every_question_has_the_columns_and_a_default(self):
        text = _section_text(5)
        rows = [line for line in text.splitlines() if line.startswith("| **Q-")]
        assert rows
        for row in rows:
            cells = re.split(r"(?<!\\)\|", row)[1:-1]
            assert len(cells) == 4, row[:60]
            assert all(c.strip() for c in cells), row[:60]

    def test_every_cited_question_is_defined_in_section_5(self):
        defined = set(re.findall(r"^\| \*\*(Q-[A-Z0-9]+)\*\*", _section_text(5), re.M))
        before_appendix = TEXT.split("\n## 8. ", 1)[0]
        cited = set(re.findall(r"\bQ-[A-Z][A-Z0-9]+\b", before_appendix))
        assert cited <= defined, sorted(cited - defined)

    def test_the_answered_new_decisions_question_says_so(self):
        row = re.search(r"^\| \*\*Q-NEW\*\*.*$", _section_text(5), re.M).group(0)
        assert "ANSWERED 3 November 2026" in row


class TestTheCarriedOverPlan:
    """Section 8 is the older plan word for word, so that no measured fact
    is lost; sections 1-7 cite it by tag (BLK S6, item 1, I1, M5)."""

    @pytest.mark.parametrize(
        "heading",
        [
            "### 8.0 How a document leaves",
            "### 8.1 Item 1:",
            "### 8.2 Item 2:",
            "### 8.3 Item 3:",
            "### 8.4 Item 4:",
            "#### Plan section 1. Target architecture",
            "#### Plan section 2. Security invariants",
            "#### Plan section 3. Ordered refactor steps",
            "#### Plan section 5. Decided",
            "#### Plan section 6. Measurements",
            "#### Plan section 7. Estimated size",
            "#### Facts and requirements carried from items removed",
        ],
    )
    def test_the_heading_is_present(self, heading):
        assert any(line.startswith(heading) for line in LINES), heading

    def test_the_invariants_and_steps_the_tiers_cite_exist(self):
        text = _section_text(8)
        for n in range(1, 9):
            assert re.search(rf"^\| I{n} \|", text, re.M), f"I{n}"
        for n in range(0, 21):
            assert re.search(rf"^\*\*S{n}\. ", text, re.M), f"S{n}"
        for n in range(1, 15):
            assert re.search(rf"^\| M{n} \|", text, re.M), f"M{n}"

    def test_a_done_step_says_so(self):
        text = _section_text(8)
        assert re.search(r"^\*\*S0\. .*DONE", text, re.M)
        assert re.search(r"^\*\*S2\. .*DONE", text, re.M)

    def test_the_measured_agent_loop_runs_survive(self):
        """The runs cost an afternoon of somebody's GPU each; losing them
        to a bad edit is the failure this item exists to prevent."""
        text = _section_text(8)
        for run in ("FOURTH RUN", "FIFTH RUN", "SIXTH RUN", "SEVENTH RUN"):
            assert run in text, run


class TestOneFile:
    def test_the_old_planning_file_is_gone(self):
        assert not (ROOT / "BLOCKING.md").exists()

    @pytest.mark.parametrize("doc", ["CLAUDE.md", "AGENTS.md", "PRINCIPLES.md", "RULES.md", "README.md"])
    def test_the_rules_documents_name_the_one_planning_file(self, doc):
        text = (ROOT / doc).read_text()
        assert "ROADMAP.md" in text, doc
        assert "BLOCKING.md" not in text, doc

    def test_claude_md_describes_how_the_roadmap_is_organised(self):
        text = (ROOT / "CLAUDE.md").read_text()
        for word in ("Tier 0", "task cards", "blocked on a", "waves"):
            assert word in text, word
