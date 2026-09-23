"""
Every operator the validator accepts is handled or declined, per adapter.

THE SAME CLASS OF BUG AS test_step_vocabulary_consistency.py, which
exists because `aggregate_object` had a handler and a prompt entry and
no branch in the parser -- so a correctly chosen step was silently
converted into a finish. Each side had its own passing tests; nobody
tested that they described the same vocabulary.

Filter operators are declared in the same shape. core/filters.py's
OPERATOR_TYPES says what a caller may send; each adapter decides
separately what it can push down to storage.

THE TWO SETS ARE ALLOWED TO DIFFER, and that is the part worth being
precise about. UnsupportedFilter exists so an adapter can decline an
operator it cannot express, and the mediator then applies the condition
in Python -- verified, not assumed: `relative_date` is accepted by the
validator, has no SQL branch, and is declined at
adapters/sqlite_adapter.py's fall-through.

WHAT IS NOT ALLOWED is silence. An operator that falls off the end of a
clause builder without raising would produce a query missing its
condition -- every row returned, reported as a filtered result. A wrong
answer reporting success, which is the failure this project keeps
finding.
"""

import pytest

from core.filters import OPERATOR_TYPES, FieldFilter, UnsupportedFilter

# A value of roughly the right shape for each operator, so the clause
# builder gets far enough to either build SQL or decline. The point is
# never the value.
SAMPLE = {
    "equals": "x",
    "contains": "x",
    "in": ["x"],
    "not_in": ["x"],
    "range": {"min": 1, "max": 2},
    "date_range": {"start": "2026-01-01", "end": "2026-12-31"},
    "relative_date": {"since_days_ago": 30},
}


def test_the_sample_covers_every_declared_operator():
    """A guard on this test rather than on the code.

    A new operator added to OPERATOR_TYPES and not to SAMPLE would
    silently drop out of the checks below -- the test would keep
    passing while covering less.
    """
    assert set(SAMPLE) == set(OPERATOR_TYPES)


@pytest.mark.parametrize("operator", sorted(OPERATOR_TYPES))
def test_the_sqlite_adapter_handles_or_declines_every_operator(operator):
    """Never silence.

    Either SQL comes back, or UnsupportedFilter says why not. What must
    not happen is a clause builder returning None or an empty string,
    which produces a query missing its condition -- every row returned,
    reported as a filtered result.
    """
    from adapters.sqlite_adapter import _clause_for

    try:
        clause, _values = _clause_for(FieldFilter("f", operator, SAMPLE[operator]))
    except UnsupportedFilter:
        return  # declined, honestly
    except NotImplementedError:  # pragma: no cover - would be a real gap
        pytest.fail(f"{operator!r} raises NotImplementedError rather than UnsupportedFilter")

    assert clause, f"{operator!r} produced an empty clause rather than declining"
    assert "f" in clause, f"{operator!r} produced a clause not mentioning the field"


@pytest.mark.parametrize("operator", sorted(OPERATOR_TYPES))
def test_the_mirror_adapter_handles_or_declines_every_operator(operator):
    # The second adapter, and the reason this is a class-level test
    # rather than one about SQLite. A third adapter would be caught by
    # the same shape.
    from core.mirror.iceberg_reader import IcebergNamespaceReader

    # The mechanics moved to the shared reader (GOLD-3).
    adapter = IcebergNamespaceReader.__new__(IcebergNamespaceReader)
    try:
        term = adapter._term_for(FieldFilter("f", operator, SAMPLE[operator]))
    except UnsupportedFilter:
        return
    except NotImplementedError:  # pragma: no cover - would be a real gap
        pytest.fail(f"{operator!r} raises NotImplementedError rather than UnsupportedFilter")

    assert term is not None, f"{operator!r} produced no term rather than declining"


def test_an_unknown_operator_is_declined_not_ignored():
    """THE CONTROL, and the bug this whole file is shaped against.

    An operator no adapter knows must not fall through to a query with
    no condition. It cannot reach here through the validator -- that is
    what OPERATOR_TYPES is for -- so this asserts the LAST line of
    defence still holds if it ever did.
    """
    from adapters.sqlite_adapter import _clause_for

    with pytest.raises((UnsupportedFilter, KeyError, ValueError)):
        _clause_for(FieldFilter("f", "definitely_not_an_operator", "x"))
