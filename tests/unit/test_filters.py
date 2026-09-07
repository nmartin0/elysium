"""
The filter vocabulary.

Elysium's filter was equality only -- one value per field -- so
selecting two values on a chart could not be expressed at all. This is
the closed set of operators that replaces it.

CLOSED DELIBERATELY. Seven operators, each added because a real
interaction needs it, rather than a general expression language. An
open one would have to be parsed and sanitised, and the thing being
parsed decides which rows a caller sees. Every operator here maps to
one SQL construct with bound parameters, so there is nothing to
sanitise.
"""

from datetime import UTC, datetime

import pytest

from core.ontology.filters import (
    FieldFilter,
    FilterError,
    parse_filters,
    resolve_relative_date,
    validate_filter,
)

# --- Parsing -------------------------------------------------------------


def test_the_legacy_dict_shape_still_means_equality():
    # Every existing caller passes {field: value}. Rewriting them all in
    # the change that introduces the vocabulary would make one commit do
    # two things.
    assert parse_filters({"region": "us-west"}) == [
        FieldFilter(field="region", operator="equals", value="us-west")
    ]


def test_an_absent_filter_is_no_filter():
    assert parse_filters(None) == []


def test_an_unknown_operator_names_the_known_ones():
    # An author reaching for one that does not exist needs to see what
    # does, or they will try another spelling of the same wrong thing.
    with pytest.raises(FilterError, match="known operators"):
        parse_filters([{"field": "region", "operator": "regex", "value": ".*"}])


def test_a_condition_missing_its_parts_says_which():
    with pytest.raises(FilterError, match=r"\['operator'\]"):
        parse_filters([{"field": "region"}])


# --- Set operators -------------------------------------------------------


def test_in_takes_a_list():
    condition = parse_filters(
        [{"field": "region", "operator": "in", "value": ["us-west", "us-east"]}]
    )[0]

    validate_filter(condition, "string")


@pytest.mark.parametrize("operator", ["in", "not_in"])
def test_an_empty_set_is_rejected(operator):
    # THE reason this is not tolerated: an empty set means "match
    # nothing" for `in` and "match everything" for `not_in` -- opposite
    # outcomes from the same mistake. Guessing which was intended is
    # how a filter silently widens.
    with pytest.raises(FilterError, match="non-empty list"):
        validate_filter(FieldFilter("region", operator, []), "string")


# --- Ranges --------------------------------------------------------------


def test_a_range_may_be_open_at_either_end():
    validate_filter(FieldFilter("amount", "range", {"min": 10}), "number")
    validate_filter(FieldFilter("amount", "range", {"max": 10}), "number")


def test_a_range_with_neither_bound_is_rejected():
    with pytest.raises(FilterError, match="min, max, or both"):
        validate_filter(FieldFilter("amount", "range", {}), "number")


def test_an_inverted_range_is_rejected():
    # Matches nothing, which is more likely a mistake than an intent --
    # and a filter that silently returns zero rows is hard to debug.
    with pytest.raises(FilterError, match="greater than max"):
        validate_filter(FieldFilter("amount", "range", {"min": 5, "max": 1}), "number")


def test_a_range_on_a_string_field_is_rejected():
    with pytest.raises(FilterError, match="applies to"):
        validate_filter(FieldFilter("name", "range", {"min": 1}), "string")


def test_a_field_with_no_declared_type_is_not_second_guessed():
    # data_type is optional. Without one there is no expectation to
    # violate, and inventing one would reject valid schemas -- the same
    # bargain the mutation-value check makes.
    validate_filter(FieldFilter("mystery", "range", {"min": 1}), None)


# --- Dates ---------------------------------------------------------------


def test_a_date_range_needs_real_iso_dates():
    validate_filter(
        FieldFilter("created", "date_range", {"start": "2026-01-01"}), "string"
    )

    with pytest.raises(FilterError, match="not a valid ISO-8601 date"):
        validate_filter(
            FieldFilter("created", "date_range", {"start": "last tuesday"}), "string"
        )


def test_relative_days_must_be_whole_and_not_negative():
    validate_filter(
        FieldFilter("created", "relative_date", {"since_days_ago": 7}), "string"
    )

    with pytest.raises(FilterError, match="cannot be negative"):
        validate_filter(
            FieldFilter("created", "relative_date", {"since_days_ago": -1}), "string"
        )
    with pytest.raises(FilterError, match="whole number of days"):
        validate_filter(
            FieldFilter("created", "relative_date", {"since_days_ago": 1.5}), "string"
        )


def test_a_boolean_is_not_a_number_of_days():
    # bool is a subclass of int in Python, so `since_days_ago: true`
    # would otherwise pass as 1 -- a value nobody meant to write.
    with pytest.raises(FilterError, match="whole number of days"):
        validate_filter(
            FieldFilter("created", "relative_date", {"since_days_ago": True}), "string"
        )


def test_an_inverted_relative_range_is_rejected():
    with pytest.raises(FilterError, match="matches nothing"):
        validate_filter(
            FieldFilter("created", "relative_date",
                        {"since_days_ago": 3, "until_days_ago": 7}),
            "string",
        )


def test_relative_dates_resolve_in_utc_from_a_fixed_reference():
    # Resolved SERVER-side in UTC, so a saved search means the same
    # thing to everyone who opens it. Browser-local would make "the
    # last 7 days" differ by timezone -- a search saved in Berlin and
    # opened in Denver would quietly return a different set.
    #
    # `now` is pinned rather than read from the clock: computing the
    # expectation from datetime.now() would assert the same arithmetic
    # twice and pass whatever the code did.
    resolved = resolve_relative_date(
        {"since_days_ago": 7, "until_days_ago": 1},
        now=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )

    assert resolved["start"].startswith("2026-08-31")
    assert resolved["end"].startswith("2026-09-06")


def test_an_open_ended_relative_range_leaves_the_other_side_none():
    resolved = resolve_relative_date(
        {"since_days_ago": 30}, now=datetime(2026, 9, 7, tzinfo=UTC)
    )

    assert resolved["start"].startswith("2026-08-08")
    assert resolved["end"] is None


# --- Text ----------------------------------------------------------------


def test_contains_needs_a_non_empty_string():
    validate_filter(FieldFilter("name", "contains", "ada"), "string")

    with pytest.raises(FilterError, match="non-empty string"):
        validate_filter(FieldFilter("name", "contains", ""), "string")


# --- The error type ------------------------------------------------------


def test_a_filter_error_is_a_value_error():
    # So callers already catching ValueError -- the API's own 400 path
    # among them -- keep working without change.
    assert issubclass(FilterError, ValueError)
