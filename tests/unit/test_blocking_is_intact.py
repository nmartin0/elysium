"""
BLOCKING.md keeps its shape.

WHY THIS EXISTS, and it is not hypothetical. Patch 493 inserted two
rows into the consumed-documents table and in doing so DELETED the
line `# Blocked on a decision` and the heading of item 1 -- the single
most important entry in the file. Seven patches shipped after that
with the main heading gone and item 1 reduced to an orphan "all."
dangling under a table.

NOTHING NOTICED. Not the linter, which does not read Markdown. Not me:
I checked line lengths and reference counts after every edit and never
once checked that the document still had its sections.

THE EDITS THAT CAUSE THIS compute an insertion point from a string
index and write around it. They are easy to get wrong by one line, and
the damage is invisible in a diff that is mostly additions.

This cannot judge whether the content is right, only that the skeleton
survived -- which is exactly the failure that happened, and exactly
the one reading did not catch.
"""

import re
from pathlib import Path

import pytest

TEXT = Path("BLOCKING.md").read_text()
LINES = TEXT.splitlines()
ITEM = re.compile(r"^## (\d+)\.(.*)$")


def _numbered():
    return [(int(m.group(1)), m.group(2)) for m in
            (ITEM.match(line) for line in LINES) if m]


class TestTheSectionsExist:
    @pytest.mark.parametrize("heading", [
        "# Blocking",
        "# Blocked on a decision",
        "# Blocked on a machine or a person running something",
        "# Blocked because it is product direction",
        "# Not blocked, and not here",
    ])
    def test_the_top_level_heading_is_present(self, heading):
        """Each is a category. Losing one silently reclassifies
        everything under it."""
        assert any(line.strip() == heading for line in LINES), heading

    def test_item_1_is_the_first_numbered_item(self):
        """It outranks the rest, and it is the one patch 493
        beheaded.

        IT NAMED `F-02` UNTIL THAT WAS BUILT. Pinning the identity of
        whatever happens to be first was pinning a fact with a
        lifetime, and it expired the moment the top item shipped. What
        this file is for is the SHAPE -- that there is a first item and
        the numbering starts at one -- so that is what it checks now."""
        numbered = _numbered()

        assert numbered, "no numbered items at all"
        assert numbered[0][0] == 1
        assert numbered[0][1].strip(), "item 1 has no title"


class TestTheNumberingIsSound:
    def test_every_number_is_present_once_and_in_order(self):
        """A gap means an item was overwritten by an insertion."""
        numbers = [n for n, _ in _numbered()]

        assert numbers == sorted(numbers), f"out of order: {numbers}"
        assert numbers == list(range(1, len(numbers) + 1)), (
            f"gap or duplicate: {numbers}")

    def test_no_item_heading_is_empty(self):
        for number, title in _numbered():
            assert title.strip(), number


class TestTheTableIsAboveTheItems:
    def test_consumed_documents_are_listed(self):
        rows = [line for line in LINES
                if line.startswith("| `") and line.endswith("|")]

        assert len(rows) >= 15, f"only {len(rows)} consumed rows"

    def test_the_table_ends_before_the_first_section(self):
        """THE EXACT FAILURE: a row inserted after the table's last
        line landed on the heading that followed it."""
        last_row = max(n for n, line in enumerate(LINES)
                       if line.startswith("| `"))
        first_section = min(n for n, line in enumerate(LINES)
                            if line.strip() == "# Blocked on a decision")

        assert last_row < first_section
        between = [line.strip() for line in LINES[last_row + 1:first_section]]
        assert all(text in ("", "---") for text in between), between


class TestEveryItemSaysWhatItWaitsOn:
    def test_each_numbered_item_has_a_blocked_on_line(self):
        """An item with no blocker is not blocked, and belongs in the
        code rather than in this file."""
        parts = re.split(r"^## (\d+)\. ", TEXT, flags=re.M)[1:]
        pairs = list(zip(parts[::2], parts[1::2], strict=True))
        missing = [number for number, body in pairs
                   if "Blocked on:" not in body]

        assert missing == [], f"items with no 'Blocked on:': {missing}"


class TestCrossReferencesPointSomewhere:
    """`item N` in the prose must name an item that exists.

    WHY THIS WAS ADDED. Removing a resolved item renumbers everything
    after it, and every `item N` written before the removal then points
    one place too high. Nothing caught that; the structural checks pass
    on a file whose internal references are all off by one.

    IT ALSO FOUND ONE THAT WAS WRONG FROM THE DAY IT WAS WRITTEN.
    Object Explorer's entry said "saving and acting on a selection ...
    the last of those is the same thing as item 23 below", and item 23
    was the plugin API. It had never pointed at Saved SELECTIONS.

    This cannot tell whether a reference points at the RIGHT item, only
    that it points at one. The wrong-from-birth case was found by
    reading what each number resolved to, which is the step this test
    makes cheap rather than the one it replaces.
    """

    def test_every_referenced_item_exists(self):
        numbers = {number for number, _ in _numbered()}
        body = TEXT.split("# Blocked on a decision", 1)[1]
        referenced = {int(m) for m in re.findall(r"item (\d+)", body)}
        missing = sorted(referenced - numbers)

        assert missing == [], f"references to items that do not exist: {missing}"

    def test_no_item_refers_to_itself(self):
        """A self-reference is what an off-by-one renumbering produces
        when an item is removed immediately before it."""
        parts = re.split(r"^## (\d+)\. ", TEXT, flags=re.M)[1:]
        for number, body in zip(parts[::2], parts[1::2], strict=True):
            assert f"item {number}" not in body, f"item {number} refers to itself"

