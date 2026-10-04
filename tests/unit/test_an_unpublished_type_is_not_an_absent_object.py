"""
A type whose gold was never published is not a type whose objects are
all missing.

`NEW-4`. `_scan` catches `NoSuchTableError` and returns None, and
`get_raw_field` returned that same None for a row that simply is not
there. A caller could not tell the two apart, so a deployment that had
never synced answered every read as if every object were absent.

S3 DRAWS THE SAME LINE, and the cost of not drawing it is documented:
a bucket that does not exist "is indistinguishable from a cold cache:
every job fetches cold and nothing reports a fault".

THE EXCEPTION ALREADY EXISTED, which is the part worth remembering.
`find_ids`, three methods up in the same file, has raised
`GoldPublicationMissing` on exactly this condition all along -- the
two methods simply disagreed. I wrote a NEW exception type before
noticing, which would have made three names for one fault. That is the
third time in four patches the right answer was to defer to something
already there.

THE ROW CASE STILL RETURNS None, deliberately. `write_mediator`'s
uniqueness check at line 857 wants "nothing is there" as an answer,
and an exception would be wrong for it. The entry asked for a split,
not a replacement.

WHY THIS COULD NOT SHIP UNTIL THE FIXTURE AUDIT. Three tests built
their generation against an EMPTY data directory while syncing into a
different one, so every read returned `{'field': None}` and this
change turned that into a raise. They looked like breakage caused by
NEW-4; they were a fixture reading an empty lake. Fixed first, in its
own patch, which is why this one is three lines.
"""

from pathlib import Path

SOURCE = Path("core/mirror/gold_connector.py").read_text()


class TestTheTwoCasesAreSeparated:
    def test_a_missing_table_raises(self):
        i = SOURCE.index("if arrow is None:")
        block = SOURCE[i:i + 1600]

        assert "raise GoldPublicationMissing(" in block

    def test_a_missing_row_still_returns_none(self):
        i = SOURCE.index("if arrow.num_rows == 0:")
        block = SOURCE[i:i + 400]

        assert "return None" in block

    def test_they_are_no_longer_one_condition(self):
        """THE DEFECT, in one line: `if arrow is None or
        arrow.num_rows == 0: return None`."""
        assert "if arrow is None or arrow.num_rows == 0:" not in SOURCE


class TestItUsesTheExceptionThatExisted:
    def test_no_second_exception_type_was_invented(self):
        """`find_ids` has raised GoldPublicationMissing on this
        condition all along. A new name would have made three."""
        assert "class GoldTableMissing" not in SOURCE
        assert SOURCE.count("class GoldPublicationMissing") == 1

    def test_find_ids_and_get_raw_field_now_agree(self):
        """They disagreed about the same condition in the same file,
        which is how one of them came to be wrong."""
        raises = [line for line in SOURCE.splitlines()
                  if "raise GoldPublicationMissing(" in line]

        assert len(raises) >= 2, raises

    def test_the_message_names_the_remedy(self):
        """A reader seeing this needs to know it is a sync away, not a
        corruption."""
        i = SOURCE.index("if arrow is None:")
        block = SOURCE[i:i + 1600]

        assert "Run a sync to build it" in block


class TestWhatTheRowCaseProtects:
    def test_the_reason_is_recorded_beside_the_code(self):
        """The caller that needs None is a uniqueness check. Someone
        tidying this later should find out why before changing it."""
        i = SOURCE.index("if arrow.num_rows == 0:")
        block = SOURCE[i:i + 500]

        assert "uniqueness" in block
        assert "write_mediator" in block
