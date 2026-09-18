"""
A link is not an aggregatable field.

THE CRASH THIS PREVENTS, from a real query once aggregate_object became
reachable from the agent loop:

    sqlite3.OperationalError: no such column: transactions

`transactions` is a link field on Customer (Author.books here). It has a real read: grant,
so it passed authorization, then get_column_for_field() resolved it as
though it were a storage column and the adapter put it in a SELECT.

The bug predates aggregate_object being reachable -- nothing could call
this path with a link before. Making the step reachable exposed it
rather than causing it.

WHY THE GUARD IS IN THE MEDIATOR and not in next_step()'s validation:
the mediator is the enforcing side. The agent is one caller among
several, and a link is not aggregatable for any of them.
"""

import pytest

from tests.unit.test_mediator import (
    _record,
    mediator,  # noqa: F401  (fixture import)
)


def test_group_by_a_link_is_refused_with_a_usable_error(mediator):  # noqa: F811
    with pytest.raises(ValueError, match="is a link"):
        mediator.aggregate_by_field(
            _record("alice"), "Author", [], group_by="books", aggregate="count",
        )


def test_aggregating_over_a_link_is_refused(mediator):  # noqa: F811
    with pytest.raises(ValueError, match="is a link"):
        mediator.aggregate_by_field(
            _record("alice"), "Author", [], group_by=None,
            aggregate="sum", field_name="books",
        )


def test_the_error_says_what_to_do_instead(mediator):  # noqa: F811
    # The agent loop feeds a caught ValueError back to the model as an
    # observation, so the message is the recovery instruction. An error
    # that only says "no" costs a hop and teaches nothing.
    with pytest.raises(ValueError, match="search_around"):
        mediator.aggregate_by_field(
            _record("alice"), "Author", [], group_by="books", aggregate="count",
        )


def test_a_real_aggregate_still_works(mediator):  # noqa: F811
    # The control. A guard that refused everything would pass all three
    # tests above and break the feature.
    result = mediator.aggregate_by_field(
        _record("alice"), "Author", [], group_by=None, aggregate="count",
    )

    # One Author is visible to alice under MAC in the shared fixture.
    # The exact number matters less than it being a real count of the
    # AUTHORIZED set rather than of the table.
    assert result == {None: 1}


def test_an_unknown_field_is_left_to_the_existing_path(mediator):  # noqa: F811
    # Deliberately NOT handled by this guard. A name that is not in the
    # schema at all has no read: grant, so _read_fields_for_ids filters
    # it out before any SQL is built -- the grant list is acting as an
    # allowlist. Asserted so that property is noticed if it ever
    # changes, because it is what keeps a hallucinated field name from
    # reaching a query string.
    result = mediator.aggregate_by_field(
        _record("alice"), "Author", [], group_by="not_a_real_field", aggregate="count",
    )

    assert result == {}
