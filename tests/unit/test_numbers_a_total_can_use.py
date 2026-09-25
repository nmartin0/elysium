"""
A `number` column holds numbers arithmetic can use (ZOO-19, ZOO-20,
ZOO-13; PR001-R26).

WHAT float() ACCEPTS, and what the mirror therefore stored:

    "NaN"      -> nan
    "inf"      -> inf
    "-inf"     -> -inf
    "Infinity" -> inf
    "1e999"    -> inf        an OVERFLOW, silently

The last is the worst of the set, because it looks like a number that
was merely large.

WHY THIS IS NOT COSMETIC. One NaN in a column poisons every total
computed from it FOR EVER -- NaN plus anything is NaN -- and nothing
reports it. An aggregate over a million good rows and one bad one
returns NaN, and a person reads that as a system fault rather than as
one cell somebody typed wrongly years ago. An infinity does the same
to a mean, a max and every comparison.

AND `int("１２３")` IS 123, because Python accepts every Unicode decimal
digit. A mirror that quietly reads full-width digits as ASCII ones is
INFERRING what the source meant, which this file's contract forbids in
so many words: "Every rule declared, never inferred."

WHAT IS DELIBERATELY STILL ACCEPTED: leading zeros. `int("007")` is 7,
which loses the padding of a code stored as text -- but the field was
DECLARED an integer, and a zero-padded integer in a text source is
ordinary and harmless. Refusing it would break working deployments to
protect against a declaration mistake. That is ZOO-14, and it is
recorded as an owner decision rather than settled here.
"""

import math

import pytest

from core.mirror.transform import transform_rows
from core.ontology.field_types import coerce


class TestWhatANumberColumnRefuses:
    @pytest.mark.parametrize("value", ["NaN", "nan", "NAN"])
    def test_not_a_number(self, value):
        with pytest.raises(ValueError, match="NaN"):
            coerce(value, "number")

    @pytest.mark.parametrize("value", ["inf", "-inf", "Infinity", "-Infinity"])
    def test_not_an_infinity(self, value):
        with pytest.raises(ValueError, match="finite"):
            coerce(value, "number")

    def test_not_an_overflow_that_became_an_infinity(self):
        """The one that looks like an ordinary large number."""
        with pytest.raises(ValueError, match="finite"):
            coerce("1e999", "number")

    def test_a_float_nan_passed_directly_is_refused_too(self):
        """Not only strings: an adapter handing over a real float NaN
        is the same poison."""
        with pytest.raises(ValueError):
            coerce(float("nan"), "number")


class TestWhatItStillAccepts:
    @pytest.mark.parametrize("value,expected", [
        ("3.5", 3.5), ("-2", -2.0), ("0", 0.0), ("1e30", 1e30),
        ("-0.0001", -0.0001), (" 7 ", 7.0),
    ])
    def test_ordinary_numbers(self, value, expected):
        assert coerce(value, "number") == expected

    def test_the_largest_finite_float(self):
        """The boundary: refusing overflow must not refuse the biggest
        number that is still a number."""
        assert math.isfinite(coerce(str(1.7976931348623157e308), "number"))


class TestIntegerDigits:
    def test_full_width_digits_are_refused(self):
        with pytest.raises(ValueError, match="ASCII digits"):
            coerce("１２３", "integer")

    @pytest.mark.parametrize("value", ["٣", "৭", "\u0660\u0661"])
    def test_other_unicode_digit_forms_too(self, value):
        """Arabic-Indic and Bengali digits are accepted by int() just
        as readily."""
        with pytest.raises(ValueError):
            coerce(value, "integer")

    @pytest.mark.parametrize("value,expected", [
        ("7", 7), ("-3", -3), ("+4", 4), (" 12 ", 12), ("007", 7),
    ])
    def test_ordinary_integers_including_leading_zeros(self, value, expected):
        """`007` is the OWNER DECISION (ZOO-14): accepted today,
        because the field was declared an integer and a zero-padded
        one is ordinary. Pinned so the decision is visible."""
        assert coerce(value, "integer") == expected


class TestThroughTheTransform:
    """What matters operationally: a bad cell becomes named DRIFT,
    reported with its column and value, rather than a silent nan."""

    @pytest.mark.parametrize("value", ["NaN", "inf", "1e999"])
    def test_a_poisoned_number_is_reported_as_drift(self, value):
        result = transform_rows([{"id": "1", "v": value}], ["id", "v"],
                                 {"v": "number"}, {})

        assert result.has_drift
        assert result.drift[0].column == "v"

    def test_a_good_column_still_passes(self):
        result = transform_rows([{"id": "1", "v": "3.5"},
                                  {"id": "2", "v": "-2"}],
                                 ["id", "v"], {"v": "number"}, {})

        assert not result.has_drift
        assert [r["v"] for r in result.rows] == [3.5, -2.0]

    def test_no_nan_can_reach_the_mirror(self):
        """The claim in one line: whatever a source contains, a
        `number` column in the mirror holds only finite numbers."""
        rows = [{"id": str(i), "v": v} for i, v in
                enumerate(["1", "2", "3.5", "-4"])]

        result = transform_rows(rows, ["id", "v"], {"v": "number"}, {})

        assert all(math.isfinite(r["v"]) for r in result.rows)
