"""
Every declared field data type is understood everywhere it is used.

THE FOURTH CALIBRATION PROBE, after the step vocabulary, the filter
operators and the grant verbs. Same class: a vocabulary spread across
files, each side individually correct, nothing asserting they describe
the same thing.

FIELD_DATA_TYPES is the ontology's answer to "what do this field's
VALUES hold". Three other places consume it and each decides
separately what to do per type:

    coerce()            turns a source value into that type
    FIELD_DATA_TYPES    maps it to an Arrow type for the mirror
    OPERATOR_TYPES      says which filter operators accept it

ADDING A TYPE IS THE RISK, not removing one. A fifth entry --
`timestamp`, say -- would pass every existing test: the ontology would
accept it, object_type_validation would approve it, and coerce() would
raise "Unknown field data_type" only when a real sync first touched a
real row. The failure would arrive in production, on data, hours after
the change looked fine.

That is exactly how the ontology shipped without data types at all:
Account.balance read as 900.0 from a live database and '500.0' from the
mirror, and nothing compared the two.
"""

import pytest

from core.filters import OPERATOR_TYPES
from core.ontology.field_types import FIELD_DATA_TYPES, coerce

# A value of roughly the right shape per type, so coerce() gets far
# enough to convert or refuse. The point is never the value.
SAMPLE = {
    "string": "text",
    "integer": "42",
    "number": "1.5",
    "boolean": "1",
    # A MONEY-SHAPED VALUE, with a trailing zero that float would
    # discard and decimal must keep.
    "decimal": "10.50",
}


def test_the_sample_covers_every_declared_type():
    """A guard on this test rather than on the code.

    A type added to FIELD_DATA_TYPES and not to SAMPLE would silently
    drop out of the checks below -- the test would keep passing while
    covering less. The grant probe shipped with exactly this bug in an
    earlier draft.
    """
    assert set(SAMPLE) == set(FIELD_DATA_TYPES)


@pytest.mark.parametrize("data_type", sorted(FIELD_DATA_TYPES))
def test_coerce_handles_every_declared_type(data_type):
    # A type the ontology accepts and coerce() does not know raises
    # "Unknown field data_type" the first time a sync touches a real
    # row -- in production, on data, long after the change looked fine.
    result = coerce(SAMPLE[data_type], data_type)

    assert result is not None


@pytest.mark.parametrize("data_type", sorted(FIELD_DATA_TYPES))
def test_every_declared_type_has_an_arrow_type(data_type):
    # The mirror writes Arrow. A declared type with no Arrow mapping
    # cannot be stored, which is a sync failure rather than a read one.
    assert FIELD_DATA_TYPES[data_type] is not None


def test_no_filter_operator_names_a_type_that_does_not_exist():
    """The reverse direction.

    OPERATOR_TYPES restricts some operators to certain field types by
    NAME. A name that no longer exists silently restricts nothing --
    the operator becomes usable on any field, and the restriction that
    was written down stops applying.
    """
    named = set()
    for accepted in OPERATOR_TYPES.values():
        # None means "any type", which names nothing.
        if accepted:
            named |= set(accepted)

    unknown = named - set(FIELD_DATA_TYPES)

    assert not unknown, (
        f"filter operators restrict to {sorted(unknown)}, which the ontology does "
        f"not declare -- the restriction silently applies to nothing"
    )


def test_coerce_refuses_a_type_it_does_not_know():
    """THE CONTROL, and the property that makes the rest safe.

    coerce() must RAISE on an unknown type rather than pass the value
    through. Passing it through would store a source value unconverted
    and report success -- the mirror then holds a string where the
    ontology promised a number, which is the original bug.
    """
    with pytest.raises(ValueError, match="Unknown field data_type"):
        coerce("x", "definitely_not_a_type")
