"""
AUDIT_CHECKLIST.csv is readable by something other than a human.

WHY THIS EXISTS: I have broken this file twice in one day, both times
while recording a finding in it.

    a truncating edit dropped a row's status field entirely, and the
    commit message claimed an update the patch did not contain

    a status quoting a test name embedded a bare double-quote inside a
    quoted CSV field, which splits the row into nine

NEITHER SHOWED UP until something tried to read the file, and both
were invisible to `git diff` at a glance. The checklist is the record
three other agents are pointed at -- LLM3 lost most of a session to a
row that said `unverified` about something already fixed -- so a row
it cannot read is worse than a row that is merely wrong.

THIS IS A SHAPE CHECK, NOT A CONTENT ONE. It cannot tell whether a
status is TRUE. It tells you the file still parses, every row has
every column, and no id appears twice -- the three ways an edit has
actually gone wrong here.
"""

import csv
from pathlib import Path

CHECKLIST = Path("AUDIT_CHECKLIST.csv")
COLUMNS = ("id", "set", "source", "severity", "claim", "where", "probe",
            "status")


def _rows():
    with CHECKLIST.open() as handle:
        return list(csv.DictReader(handle))


class TestItParses:
    def test_the_file_is_readable(self):
        assert _rows(), "the checklist is empty or unparseable"

    def test_every_row_has_every_column(self):
        """A truncating edit drops the last field silently, and the row
        still looks fine in a diff."""
        wrong = [
            (row.get("id"), len(row)) for row in _rows()
            if len(row) != len(COLUMNS) or None in row
        ]

        assert wrong == [], f"rows with the wrong number of fields: {wrong}"

    def test_the_columns_are_the_expected_ones(self):
        with CHECKLIST.open() as handle:
            header = next(csv.reader(handle))

        assert tuple(header) == COLUMNS


class TestTheRowsAreUsable:
    def test_no_id_appears_twice(self):
        """Two rows for one finding means one of them is being
        ignored, and nobody knows which."""
        seen: dict = {}
        duplicates = []
        for row in _rows():
            if row["id"] in seen:
                duplicates.append(row["id"])
            seen[row["id"]] = True

        assert duplicates == [], f"duplicated ids: {duplicates}"

    def test_every_row_has_an_id_and_a_status(self):
        blank = [row for row in _rows()
                 if not (row["id"] or "").strip()
                 or not (row["status"] or "").strip()]

        assert blank == [], f"{len(blank)} row(s) with no id or no status"

    def test_a_status_never_contains_a_raw_newline(self):
        """A status spanning two lines reads as two rows to anything
        that splits on newlines before parsing -- which is most
        one-line greps somebody will write."""
        multiline = [row["id"] for row in _rows()
                     if "\n" in (row["status"] or "")]

        assert multiline == [], f"multi-line statuses: {multiline}"
