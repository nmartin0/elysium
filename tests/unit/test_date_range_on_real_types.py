"""
A date_range filter on a real date type, rather than on text.

THE BUG, MEASURED BEFORE THE FIX. Dates stored as strings compare
lexically, and `date_range` compares them as TEXT -- correct for
padded ISO-8601, wrong for everything else:

    '2026-1-5' > '2026-02-01'  is True

So a filter for "after February" returned a January row and said
nothing. The operator's own comment acknowledged the risk -- "a
non-ISO date column would compare wrongly" -- and its validator checks
the FILTER's bounds with fromisoformat while never checking the STORED
data.

ON A REAL `date` THE RISK IS GONE BY CONSTRUCTION: the mirror stores
date32, Iceberg compares chronologically, and a value that is not a
date cannot be stored at all.
"""

import pytest

from core.filters import FieldFilter, FilterError, validate_filter


def _filter(operator="date_range", value=None):
    return FieldFilter(
        field="when_", operator=operator,
        value=value if value is not None else {"start": "2026-02-01"},
    )


class TestTheOperatorAcceptsTheRealTypes:
    @pytest.mark.parametrize("declared", ["date", "timestamp", "timestamptz"])
    def test_a_temporal_field_may_be_range_filtered(self, declared):
        validate_filter(_filter(), declared)

    @pytest.mark.parametrize("declared", ["date", "timestamp", "timestamptz"])
    def test_relative_date_too(self, declared):
        # THE REAL SHAPE, read from the validator rather than assumed:
        # since_days_ago / until_days_ago, not a named period.
        validate_filter(
            _filter(operator="relative_date", value={"since_days_ago": 7}),
            declared,
        )

    def test_string_still_works(self):
        """THE CASE THIS OPERATOR WAS BUILT FOR, when no date type
        existed. Removing it would break every ontology that already
        declares a date column as text."""
        validate_filter(_filter(), "string")


class TestItStillRefusesWhatItAlwaysDid:
    def test_a_number_cannot_be_date_ranged(self):
        with pytest.raises(FilterError):
            validate_filter(_filter(), "number")

    def test_a_boolean_cannot_be_date_ranged(self):
        with pytest.raises(FilterError):
            validate_filter(_filter(), "boolean")

    def test_a_malformed_bound_is_still_refused(self):
        # The validator checks the filter's own bounds, which it always
        # did and still should.
        with pytest.raises(FilterError):
            validate_filter(_filter(value={"start": "not-a-date"}), "date")

    def test_neither_bound_is_refused(self):
        """BOTH ABSENT WOULD MATCH NOTHING AND REPORT NO ERROR, which
        the adapter's own comment calls the hardest kind of wrong
        answer."""
        with pytest.raises(FilterError):
            validate_filter(_filter(value={}), "date")
