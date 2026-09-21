"""
Constraints on the values a field may hold.

FOUNDRY'S VALUE TYPES: "a minimum value, maximum value, or range of
allowed values", a regex, an enum -- enforcing "data validation in a
manner reusable across the platform". Declared on the FIELD, so every
action that sets it is checked.

ITS ROADMAP ENTRY NAMED ITS TRIGGER -- "an action form" -- and action
forms exist now, so this was due rather than deferred.
"""

from decimal import Decimal

import pytest

from core.ontology.constraints import validate_constraints, violation


def _field(data_type="string", **constraints):
    return {"type": "data", "data_type": data_type, "constraints": constraints}


class TestEachKindOfConstraint:
    def test_min_and_max_on_a_decimal(self):
        amount = _field("decimal", min="0", max="1000")

        assert violation(amount, "49.99") is None
        assert "below the minimum" in violation(amount, "-0.01")
        assert "above the maximum" in violation(amount, Decimal("1000.01"))

    def test_numbers_compare_as_numbers_not_text(self):
        """AS TEXT, "9" SORTS ABOVE "10" -- so a text comparison would
        refuse 9 under a maximum of 10. The case that actually tells the
        two apart; the date test below cannot, because padded ISO dates
        sort correctly as text too. A control comparing as text failed
        only one test until this existed."""
        assert violation(_field("decimal", max="10"), "9") is None
        assert violation(_field("integer", min=2), "10") is None

    def test_dates_compare_as_dates(self):
        """Coerced, they are dates. NOTE: padded ISO dates also sort
        correctly as TEXT, so this pins date comparison working, not the
        difference from text -- the numeric test above does that."""
        due = _field("date", min="2026-09-01")

        assert violation(due, "2026-10-01") is None
        assert "below the minimum" in violation(due, "2026-08-31")

    def test_lengths_on_a_string(self):
        code = _field(min_length=3, max_length=3)

        assert violation(code, "USA") is None
        assert "shorter" in violation(code, "US")
        assert "longer" in violation(code, "USAX")

    def test_a_pattern_must_match_the_whole_value(self):
        """FULL MATCH. A pattern that passes on any substring lets
        almost anything through."""
        # ONE backslash. Written through a shell heredoc first, this held
        # two -- a class excluding the LETTER s rather than whitespace --
        # and a sentence with no "s" in it fully matched.
        email = _field(pattern=r"[^@\s]+@[^@\s]+")

        assert violation(email, "a@b.com") is None
        assert "does not match" in violation(email, "not an email a@b.com trailing")

    def test_one_of(self):
        category = _field(one_of=["food", "travel"])

        assert violation(category, "food") is None
        assert "not one of" in violation(category, "rent")

    def test_one_of_compares_values_not_spellings(self):
        """"5" AND 5 ARE ONE INTEGER."""
        tier = _field("integer", one_of=[1, 5, 10])

        assert violation(tier, "5") is None

    def test_null_is_not_checked(self):
        """CLEARING A FIELD is not a value out of range."""
        assert violation(_field("decimal", min="0"), None) is None

    def test_a_value_that_is_not_the_type_is_named(self):
        assert "not a valid decimal" in violation(_field("decimal", min="0"), "abc")


def _schema(**constraints):
    return {"T": {"fields": {"f": {"type": "data", **constraints}}}}


class TestMistakesStopTheLoad:
    @pytest.mark.parametrize(("declaration", "expected"), [
        ({"constraints": {"minimum": 1}}, "unknown constraint"),
        ({"constraints": {"min": 1}}, "does not apply to a string"),
        ({"data_type": "string", "constraints": {"pattern": "("}}, "does not compile"),
        ({"data_type": "decimal", "constraints": {"min": "5", "max": "1"}}, "above `max`"),
        ({"data_type": "decimal", "constraints": {"min": "abc"}}, "not a decimal"),
        ({"constraints": {"min_length": -1}}, "whole number"),
        ({"constraints": {"min_length": 5, "max_length": 2}}, "above `max_length`"),
        ({"constraints": {"one_of": []}}, "non-empty list"),
        ({"data_type": "integer", "constraints": {"one_of": ["x"]}}, "not a integer"),
        ({"constraints": {}}, "non-empty mapping"),
    ])
    def test_each_is_refused(self, declaration, expected):
        """A MALFORMED CONSTRAINT silently never fires, or fires on
        everything -- worse than none."""
        with pytest.raises(ValueError, match=expected):
            validate_constraints(_schema(**declaration))

    def test_a_valid_block_passes(self):
        validate_constraints(_schema(data_type="decimal", constraints={"min": "0", "max": "10"}))
