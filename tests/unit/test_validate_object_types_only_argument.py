"""
`only` takes an object type NAME, and refuses anything else.

WHY THIS EXISTS: I wrote `validate_object_types(schema, {})` twice
while checking F-19, and twice concluded from its clean return that an
invalid ontology was being accepted.

IT IS NOT. `only` narrows validation to ONE object type by comparing
it against each name, so a value that matches nothing -- an empty
dict, a list, a set -- validates NOTHING and returns as though the
schema were fine.

THE CONSEQUENCE WAS A WHOLE PATCH THAT SHOULD NOT HAVE EXISTED. I
reproduced a defect that did not reproduce, wrote a duplicate of a
check `_validate_security()` already performs, and only found out when
four existing tests started failing because my duplicate shadowed
theirs with different wording. The reproduction was wrong, not the
code.

AN ARGUMENT WHOSE WRONG VALUE LOOKS LIKE SUCCESS is worth one line to
refuse. This is the cheapest kind of fix: it cannot make anything
work, it can only stop a wrong call from looking like a right one.
"""

import pytest

from core.ontology.object_type_validation import validate_object_types

SCHEMA = {
    "Customer": {
        "id_field": "id", "security": {"field": "region"},
        "storage": {"silo": "p", "table": "t", "id_column": "id"},
        "fields": {"id": {"type": "data"}, "region": {"type": "data"}},
    }
}
BROKEN = {
    "Order": {
        "id_field": "id", "security": {"via_field": "nosuchfield"},
        "storage": {"silo": "p", "table": "o", "id_column": "id"},
        "fields": {"id": {"type": "data"}},
    }
}


class TestWhatOnlyAccepts:
    def test_none_validates_everything(self):
        validate_object_types(SCHEMA)

    def test_a_name_validates_that_type(self):
        validate_object_types(SCHEMA, "Customer")

    def test_a_name_that_matches_nothing_is_allowed(self):
        """Narrowing to a type that is not in this schema is a
        legitimate no-op -- the caller may hold several schemas."""
        validate_object_types(SCHEMA, "NotHere")


class TestWhatItRefuses:
    @pytest.mark.parametrize("only", [{}, [], set(), 0, {"Customer": {}}])
    def test_a_non_name_is_a_TypeError(self, only):
        with pytest.raises(TypeError, match="object type NAME"):
            validate_object_types(SCHEMA, only)

    def test_the_message_says_why_it_matters(self):
        """"Wrong type" is not the point. The point is that the wrong
        type LOOKS LIKE SUCCESS."""
        with pytest.raises(TypeError, match="validates nothing"):
            validate_object_types(SCHEMA, {})


class TestTheCaseThatMisledMe:
    def test_a_broken_schema_is_refused_when_called_properly(self):
        """The check was there all along."""
        with pytest.raises(ValueError, match="unknown field"):
            validate_object_types(BROKEN)

    def test_and_the_wrong_call_no_longer_hides_it(self):
        """Before: this returned cleanly and looked like a clean bill
        of health for a schema that is not valid."""
        with pytest.raises(TypeError):
            validate_object_types(BROKEN, {})
