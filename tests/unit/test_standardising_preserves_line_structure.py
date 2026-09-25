"""
Standardisation tidies text without destroying it (PA001-S1).

WHAT THE DEFAULT DID. `collapse_whitespace` was
`" ".join(value.split())`, which treats every kind of whitespace
alike. It is ON by default for every declared string field, so an
address stored as

    12 High St
    London
    E1 6AN

arrived in silver as "12 High St London E1 6AN", and a note with
paragraphs became one line. Nothing declared that.

THE CONTRADICTION IS WITH OUR OWN RULE. MEDALLION_PIPELINE.md S1 says
standardisation is "meaning-preserving only" -- NFC, trim, collapse
whitespace, NO case folding, NO accent stripping -- precisely because
silver is what gets SERVED and what a person edits. Flattening an
address is not meaning-preserving, and a user who opens a prefilled
field and saves it writes the flattened version BACK TO THE SOURCE.
That is the part that makes this more than cosmetic: the mirror is
supposed to be a copy, and this let it quietly rewrite the original.

WHAT IS KEPT: runs of spaces and tabs still collapse, each line is
still trimmed, and blank lines at the edges still go -- the tidying
the rule was wanted for. CRLF and CR become LF, which IS
meaning-preserving and stops three spellings of one line break
reaching every later comparison.
"""

import pytest

from core.mirror.standardise import DEFAULTS, rules_for, standardise


class TestStructureSurvives:
    @pytest.mark.parametrize("value", [
        "a note\nsecond line",
        "12 High St\nLondon\nE1 6AN",
        "para one\n\npara two",
        "- item\n- item\n- item",
    ])
    def test_line_breaks_are_kept(self, value):
        assert "\n" in standardise(value, DEFAULTS)

    def test_an_address_arrives_as_it_was_written(self):
        address = "12 High St\nLondon\nE1 6AN"

        assert standardise(address, DEFAULTS) == address

    def test_a_blank_line_inside_the_text_is_the_authors(self):
        """Paragraph breaks are meaning. Only the edges are tidying."""
        assert standardise("a\n\nb", DEFAULTS) == "a\n\nb"


class TestTheTidyingStillHappens:
    @pytest.mark.parametrize("value,expected", [
        ("double  space", "double space"),
        ("code\tblock", "code block"),
        ("  padded  ", "padded"),
        ("trailing   \nnext", "trailing\nnext"),
        ("  \n\nreal text\n\n  ", "real text"),
        ("a     b", "a b"),
    ])
    def test_horizontal_whitespace_collapses(self, value, expected):
        assert standardise(value, DEFAULTS) == expected


class TestLineEndingsAreNormalised:
    @pytest.mark.parametrize("value", ["line1\r\nline2", "line1\rline2",
                                        "line1\nline2"])
    def test_every_spelling_of_a_line_break_becomes_one(self, value):
        """Three spellings of the same break otherwise make every
        later comparison -- a match key, a diff, an equality filter --
        depend on which editor last touched the row."""
        assert standardise(value, DEFAULTS) == "line1\nline2"


class TestWhatWasAlreadyRight:
    def test_non_strings_pass_through(self):
        for value in (3, 2.5, True, None):
            assert standardise(value, DEFAULTS) == value

    def test_a_field_can_still_opt_out_entirely(self):
        assert rules_for({"standardise": False}) is None
        assert standardise("  as   written  ", None) == "  as   written  "

    def test_sentinels_still_become_null(self):
        rules = dict(DEFAULTS, null_if=("N/A",))

        assert standardise("  N/A  ", rules) is None

    def test_unicode_is_still_normalised(self):
        composed = standardise("cafe\u0301", DEFAULTS)

        assert composed == "caf\u00e9"

    def test_trim_without_collapse_is_unchanged(self):
        rules = dict(DEFAULTS, collapse_whitespace=False, trim=True)

        assert standardise("  a  b  ", rules) == "a  b"


class TestTheRuleMatchesItsDocumentation:
    def test_meaning_preserving_means_what_it_says(self):
        """MEDALLION_PIPELINE.md S1 lists what standardisation may do.
        This test exists so a future widening of the default has to
        argue with the document rather than quietly contradict it."""
        from pathlib import Path

        text = Path("MEDALLION_PIPELINE.md").read_text()

        assert "meaning-preserving only" in text
        # and the value that proves we now obey it
        assert standardise("12 High St\nLondon", DEFAULTS) == "12 High St\nLondon"
