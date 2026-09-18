"""
`decimal_places` belongs on a `decimal` field.

MISSED WHEN THE TYPE WAS ADDED, and caught by declaring a real money
field and watching the linter refuse it:

    decimal_places is only meaningful on a numeric field, but this one
    is 'decimal'

A decimal field is the one MOST likely to need it. Two screens showing
'10.5' and '10.50' for the same column is exactly the inconsistency
decimal_places exists to prevent.
"""

import pytest

from core.ontology.object_type_validation import _validate_decimal_places


def _check(data_type):
    _validate_decimal_places(
        "Transaction.amount", {"decimal_places": 2, "data_type": data_type},
    )


class TestWhichTypesMayDeclareIt:
    @pytest.mark.parametrize("data_type", ["number", "integer", "decimal"])
    def test_numeric_types_may(self, data_type):
        _check(data_type)

    @pytest.mark.parametrize("data_type", ["string", "boolean", "date"])
    def test_others_may_not(self, data_type):
        # Saying so at load is kinder than leaving an author to notice
        # the field renders unchanged.
        with pytest.raises(ValueError, match="only meaningful on a numeric"):
            _check(data_type)

    def test_an_undeclared_type_is_left_alone(self):
        # A field with no data_type has not opted into the check.
        _validate_decimal_places("Thing.x", {"decimal_places": 2})
