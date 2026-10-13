"""
Properties that must hold for EVERY input, checked with hypothesis (DEP-2).

An example-based test checks the cases somebody thought of. These state
a rule and let hypothesis search for the input that breaks it, then
shrink that input to the smallest one that still does -- which is the
form a person can read.

Chosen where the rule is crisp and a counter-example would be a real
bug: two implementations that must agree, a value that must survive a
round trip, arithmetic that must match its exact definition.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pyarrow as pa
from hypothesis import given, settings
from hypothesis import strategies as st

from core.mirror.changelog import diff_snapshot_tables, diff_snapshots
from core.mirror.incremental import decode_mark, encode_mark, higher, read_from
from core.ontology.derived_fields import compute, derivation_of, finished

# -- the changelog's two diffs agree (R5) --------------------------------

_value = st.one_of(st.none(), st.sampled_from(["a", "b", "", "1", "x y"]))
_ids = st.one_of(st.none(), st.sampled_from([f"k{i}" for i in range(6)]))


def _rows(columns):
    return st.lists(st.fixed_dictionaries({"id": _ids, **{c: _value for c in columns}}),
                    max_size=10)


def _table(rows, columns):
    return pa.table({name: pa.array([row[name] for row in rows], pa.string())
                     for name in ["id", *columns]})


@settings(max_examples=300, deadline=None)
@given(st.data(), st.booleans(), st.booleans())
def test_the_arrow_diff_is_the_dict_diff(data, accept_deletions, before_images):
    """diff_snapshot_tables was written to give diff_snapshots' answer
    without building dicts. Any snapshot pair, either option -- the same
    ChangeSet, or a changelog records something the old one would not."""
    old_columns = data.draw(st.sampled_from([["a"], ["a", "b"]]))
    new_columns = data.draw(st.sampled_from([["a"], ["a", "b"], ["b"]]))
    previous, current = data.draw(_rows(old_columns)), data.draw(_rows(new_columns))

    expected = diff_snapshots(previous, current, "id", accept_deletions=accept_deletions,
                              before_images=before_images)
    actual = diff_snapshot_tables(_table(previous, old_columns), _table(current, new_columns),
                                  "id", accept_deletions=accept_deletions,
                                  before_images=before_images)
    assert actual == expected


# -- an incremental mark survives being stored (R2) -----------------------

_marks = st.one_of(
    st.integers(min_value=-(2**62), max_value=2**62),
    st.decimals(allow_nan=False, allow_infinity=False, places=6),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=30),
    st.dates(),
    st.datetimes(timezones=st.one_of(st.none(), st.just(UTC))),
)


@given(_marks)
def test_a_mark_comes_back_as_the_value_and_type_it_went_in_as(mark):
    """The mark goes back to the SOURCE as a query parameter, so a
    timestamp that returned as text, or an integer as a float, would be
    compared as the wrong thing."""
    decoded = decode_mark(encode_mark(mark))
    assert decoded == mark and type(decoded) is type(mark)


@given(st.lists(st.integers(), min_size=1))
def test_the_mark_is_the_largest_value_whatever_the_order(values):
    mark = None
    for value in values:
        mark = higher(mark, value)
    assert mark == max(values)


@given(st.datetimes(min_value=datetime(1900, 1, 1)), st.integers(min_value=0, max_value=86_400))
def test_a_lookback_never_moves_the_mark_forward(mark, seconds):
    assert read_from(mark, timedelta(seconds=seconds)) <= mark


# -- derived arithmetic is exact (R37) ------------------------------------

_money = st.decimals(min_value=Decimal("-1e9"), max_value=Decimal("1e9"), places=2)


@given(_money, _money)
def test_a_decimal_product_is_the_exact_product_rounded_once(price, quantity):
    derivation = derivation_of({"derived": {"multiply": ["price", "quantity"]}})
    result = finished(compute(derivation, {"price": price, "quantity": quantity}), "decimal")
    assert result == (price * quantity).quantize(Decimal("1e-9"))


@given(st.decimals(min_value=Decimal("-1e6"), max_value=Decimal("1e6"), places=2),
       st.decimals(min_value=Decimal("-1e6"), max_value=Decimal("1e6"), places=2))
def test_float_inputs_give_the_float_of_the_exact_answer(left, right):
    """What the Browse screen showed going wrong: 49.99 x 1.1 as
    54.989000000000004. For two-place inputs given as floats, the result
    is the float NEAREST the exact decimal product -- not binary float
    multiplication's answer, which can be one step away from it."""
    derivation = derivation_of({"derived": {"multiply": ["a", "b"]}})
    result = compute(derivation, {"a": float(left), "b": float(right)})
    assert result == float(left * right)


@given(st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31)),
       st.dates(min_value=date(1900, 1, 1), max_value=date(2100, 12, 31)))
def test_years_since_agrees_with_counting_birthdays(born, today):
    """Checked against an INDEPENDENT definition -- has this year's
    birthday DATE been reached -- not the formula restated. A 29 February
    birthday falls on 1 March in a common year."""
    try:
        birthday = born.replace(year=today.year)
    except ValueError:
        birthday = date(today.year, 3, 1)
    expected = today.year - born.year - (today < birthday)

    derivation = derivation_of({"derived": {"years_since": "born"}})
    assert compute(derivation, {"born": born}, today=today) == expected


# -- bronze's text decodes to the value it was given (R3) -----------------

_json_leaves = st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=8),
                         st.floats(allow_nan=False, allow_infinity=False))
_source_values = st.one_of(
    st.booleans(), st.integers(), st.floats(allow_nan=False), st.text(),
    st.binary(), st.decimals(allow_nan=False, allow_infinity=False),
    st.dates(), st.datetimes(timezones=st.one_of(st.none(), st.just(UTC))), st.times(),
    st.timedeltas(min_value=timedelta(days=-9999), max_value=timedelta(days=9999)),
    st.uuids(),
    st.recursive(_json_leaves, lambda inner: st.one_of(
        st.lists(inner, max_size=4), st.dictionaries(st.text(max_size=5), inner, max_size=4)),
        max_leaves=8),
    st.sets(st.integers(), max_size=5),
)


@given(_source_values)
def test_bronze_text_decodes_to_the_value_it_was_given(value):
    """THE ROUND TRIP R3 asked to be guaranteed: whatever a source sends,
    bronze's text and its recorded encoding give it back."""
    from core.mirror.bronze_text import bronze_encoding, bronze_text, bronze_value

    decoded = bronze_value(bronze_text(value), bronze_encoding(value))
    assert decoded == value and type(decoded) is type(value)
