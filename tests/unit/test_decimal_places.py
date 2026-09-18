"""
How many decimal places a field is worth showing.

DECLARED ON THE PROPERTY, not chosen by the UI, because the UI cannot
know. The ontology says a field is a number and says nothing about its
scale: the same `number` type carries a coordinate, a count and a
ratio, and two places is wrong for at least two of them.

Foundry puts it in the same place -- value formatting is property
metadata that transforms raw values "into more readable versions in
user applications" -- and it sits beside `visibility` and `status`
here for the same reason: all three are things an ontology author knows
and an application cannot infer.

COSMETIC, like everything else in _validate_ui_metadata. It changes how
a number is DISPLAYED and never what it is. The stored value, the value
an action writes, and the value a filter compares against are all
untouched -- rounding for display and then filtering on the rounded
figure would be a different and much worse feature.
"""

import pytest

from core.ontology.object_type_validation import validate_object_types

BASE = {
    "Reading": {
        "id_field": "reading_id",
        "storage": {"table": "readings", "id_column": "reading_id"},
        # A security block, because the validator requires one -- MAC
        # is not optional on an object type, and a fixture without it
        # fails for a reason unrelated to what these tests check.
        "security": {"field": "region"},
        "fields": {
            "reading_id": {"type": "data", "data_type": "string"},
            "region": {"type": "data", "data_type": "string"},
        },
    }
}


def _schema(field_info):
    schema = {"Reading": {**BASE["Reading"], "fields": dict(BASE["Reading"]["fields"])}}
    schema["Reading"]["fields"]["value"] = field_info
    return schema


def test_a_declared_precision_is_accepted():
    validate_object_types(_schema({"type": "data", "data_type": "number", "decimal_places": 2}))


def test_zero_places_is_allowed():
    # A count rendered "1,234" rather than "1,234.00" is exactly what
    # this is for, and zero is a real answer rather than an absent one.
    validate_object_types(_schema({"type": "data", "data_type": "integer", "decimal_places": 0}))


def test_absent_is_allowed():
    # THE CONTROL, and the overwhelmingly common case. There is no
    # sensible default, so a field saying nothing must stay valid --
    # a rule requiring it would break every existing deployment.
    validate_object_types(_schema({"type": "data", "data_type": "number"}))


def test_a_negative_count_is_refused():
    with pytest.raises(ValueError, match="between 0 and"):
        validate_object_types(_schema({"type": "data", "data_type": "number", "decimal_places": -1}))


def test_an_absurd_count_is_refused():
    with pytest.raises(ValueError, match="between 0 and"):
        validate_object_types(_schema({"type": "data", "data_type": "number", "decimal_places": 99}))


def test_true_is_refused_rather_than_read_as_one():
    # bool is an int in Python, so `decimal_places: true` would
    # otherwise mean one place -- a typo silently becoming a setting.
    with pytest.raises(ValueError, match="whole number"):
        validate_object_types(_schema({"type": "data", "data_type": "number", "decimal_places": True}))


def test_a_string_count_is_refused():
    with pytest.raises(ValueError, match="whole number"):
        validate_object_types(_schema({"type": "data", "data_type": "number", "decimal_places": "2"}))


def test_it_is_refused_on_a_non_numeric_field():
    # Declared on a string it would be silently ignored, and an author
    # who wrote it meant something by it. Saying so at load is kinder
    # than leaving them to notice the field renders unchanged.
    with pytest.raises(ValueError, match="only meaningful on a numeric field"):
        validate_object_types(_schema({"type": "data", "data_type": "string", "decimal_places": 2}))
