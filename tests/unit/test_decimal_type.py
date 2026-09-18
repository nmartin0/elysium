"""
An exact numeric type, because `number` loses money.

MEASURED, NOT FEARED. `coerce()` sends `number` through `float()`, so
'1234.56789012345678901' becomes 1234.567890123457 -- an invoice
silently becoming a different amount. Bronze stores the source as
strings, so a corrected silver can be rebuilt without re-reading the
customer's database; that is the only reason this was not urgent.

ALONGSIDE `number`, NOT REPLACING IT, which is what every layer below
us does. Foundry has Double and Decimal as separate base types,
Iceberg has double and decimal(P,S), PostgreSQL has double precision
and numeric. They answer different questions. Floats for measurement,
decimals for money.

PRECISION AND SCALE ARE FIXED at 38/9 rather than declared per field.
Per-field precision is what PostgreSQL and Iceberg allow and is not
obviously better: it makes every ontology longer, makes changing a
field's precision a migration, and lets two fields holding the same
currency disagree.
"""

import decimal

import pyarrow as pa
import pytest

from core.ontology.field_types import (
    DECIMAL_PRECISION,
    DECIMAL_SCALE,
    arrow_type_for,
    coerce,
)


class TestItKeepsWhatFloatLoses:
    def test_a_large_exact_amount_survives_decimal_and_not_number(self):
        """THE CASE THAT STARTED THIS, with a value chosen to fail.

        A first version of this test used 1234.567890123 -- thirteen
        digits, which a float holds EXACTLY, so the test passed for
        `decimal` and failed to show `number` losing anything. Floats
        carry about seventeen significant digits; the loss needs more
        than that.
        """
        exact = "12345678901234.567890123"

        assert str(coerce(exact, "decimal")) == exact
        assert str(coerce(exact, "number")) != exact

    def test_trailing_zeros_survive(self):
        """'10.50' IS NOT '10.5' TO AN ACCOUNTANT, even though the
        numbers are equal. Decimal preserves the scale it was given;
        float cannot."""
        assert str(coerce("10.50", "decimal")) == "10.50"

    def test_a_float_input_goes_through_text(self):
        """Decimal(float) INHERITS THE FLOAT'S ERROR -- Decimal(0.1) is
        0.1000000000000000055511151231257827. Rendering as text first
        is what makes this type worth having.

        Bronze stores strings so the normal path is already text; this
        guards the case where it is not.
        """
        assert coerce(0.1, "decimal") == decimal.Decimal("0.1")


class TestItRefusesRatherThanRounds:
    def test_too_many_decimal_places(self):
        # Rounding here would be the silent loss this type exists to
        # prevent.
        with pytest.raises(ValueError, match="decimal places"):
            coerce("1.0000000000001", "decimal")

    def test_too_large_to_store(self):
        with pytest.raises(ValueError, match="too large"):
            coerce("9" * 30, "decimal")

    def test_exponent_form_is_measured_by_magnitude(self):
        """A FIRST VERSION USED len(digits) AND WAS WRONG.
        Decimal('1e400').as_tuple().digits is just (1,) -- the
        magnitude lives in the exponent, so counting digits let a value
        400 places wide through to fail at Arrow instead."""
        with pytest.raises(ValueError, match="too large"):
            coerce("1e400", "decimal")

    def test_not_a_number_is_refused(self):
        """NaN AND INFINITY ARE NOT AMOUNTS. Decimal accepts both, and
        either would reach the mirror as a value no arithmetic can use.
        Found by mypy, which noticed as_tuple().exponent is a letter
        for these rather than a number."""
        with pytest.raises(ValueError, match="finite"):
            coerce("nan", "decimal")

        with pytest.raises(ValueError, match="finite"):
            coerce("inf", "decimal")

    def test_a_value_that_is_not_a_number_at_all(self):
        with pytest.raises((ValueError, decimal.InvalidOperation)):
            coerce("banana", "decimal")


class TestItFitsWhereItIsStored:
    def test_everything_accepted_survives_arrow(self):
        """THE CONTROL THAT MATTERS. Arrow refuses an oversized decimal
        at WRITE time, naming neither the column nor the row. Every
        value this coercer accepts must therefore fit, or the drift
        report loses the one thing that makes it useful."""
        arrow_type = pa.decimal128(DECIMAL_PRECISION, DECIMAL_SCALE)

        for raw in ("0", "10.50", "-1234.5", "9" * 29, "0.000000001"):
            pa.array([coerce(raw, "decimal")], type=arrow_type)

    def test_the_declared_type_maps_to_decimal128(self):
        assert arrow_type_for("decimal") == pa.decimal128(
            DECIMAL_PRECISION, DECIMAL_SCALE,
        )

    def test_null_stays_null(self):
        # A real NULL is not a type error, for decimal as for the rest.
        assert coerce(None, "decimal") is None
