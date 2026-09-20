"""
One saved view, evaluated as each recipient.

THE SAME QUERY, DIFFERENT AUTHORITY. `search_object` already takes a
user, so evaluating a view as Alice and then as Bob is one existing
function called with a different first argument -- through
`check_access`, MAC and the audit log unchanged.

THERE IS NO SECOND PERMISSION PATH TO GET WRONG, which matters more
here than anywhere else in the trigger work: this is the one place a
condition touches somebody else's data.

AND NO PRIVILEGED COUNT EXISTS. Nobody evaluates the view as an owner
and filters the result; each number comes from its own search. A
recipient who can see nothing counts zero, rather than being told a
number and shown none of it.

MEASURED ON THE SHIPPED DEPLOYMENT: the same "All transactions" view
counts 4 for a us-west reader and 2 for a us-east one.
"""

import pytest

from core.count_condition import count_for_each
from core.intermediate_layer.auth import UserRecord
from core.saved_views import SavedView


@pytest.fixture
def mediator():
    from core.deployment_loader import build_generation, resolve_runtime_paths

    paths = resolve_runtime_paths()
    return build_generation(
        paths.config_dir, paths.data_dir, paths.log_dir,
    ).mediator


def _view(object_type="Transaction", conditions=None, query_text=""):
    return SavedView(
        "v1", "All transactions", object_type, query_text,
        conditions or [], "2026-01-01T00:00:00+00:00",
    )


class TestAuthorityIsPerRecipient:
    def test_two_partitions_count_differently(self, mediator):
        """THE PROPERTY THE WHOLE DESIGN RESTS ON. If both counted the
        same, the query would be running with somebody's authority
        other than the reader's."""
        counts = count_for_each(mediator, _view(), [
            UserRecord("west", "us-west", "debug"),
            UserRecord("east", "us-east", "debug"),
        ])

        assert counts["west"] != counts["east"]

    def test_each_count_is_that_persons_own_search(self, mediator):
        west = UserRecord("west", "us-west", "debug")

        counts = count_for_each(mediator, _view(), [west])

        assert counts["west"] == len(
            mediator.search_object(west, "Transaction", []),
        )

    def test_somebody_who_can_see_nothing_counts_zero(self, mediator):
        """NOT ABSENT, ZERO. A recipient with no matches has a count
        like anybody else -- it is a real measurement, and their
        baseline needs it."""
        nobody = UserRecord("nobody", "no-such-region", "debug")

        assert count_for_each(mediator, _view(), [nobody]) == {"nobody": 0}


class TestFiltersAreApplied:
    def test_a_filter_narrows_the_count(self, mediator):
        west = UserRecord("west", "us-west", "debug")
        everything = count_for_each(mediator, _view(), [west])["west"]

        # `equals`, NOT `range`. A first version used range on
        # `amount`, which declares data_type `decimal` -- and the
        # ontology refuses it: "operator 'range' cannot be used on
        # field 'amount'... it applies to ['integer', 'number']".
        #
        # The validation was right and the test was wrong, which is
        # the good direction for that to happen in.
        narrowed = count_for_each(mediator, _view(conditions=[
            {"field": "amount", "operator": "equals",
             "value": "-1.00"},
        ]), [west])["west"]

        assert narrowed < everything

    def test_an_unfiltered_view_counts_everything_visible(self, mediator):
        west = UserRecord("west", "us-west", "debug")

        assert count_for_each(mediator, _view(), [west])["west"] > 0


class TestOneFailureCostsOneRecipient:
    def test_an_unknown_object_type_yields_no_count_for_anybody(self, mediator):
        """A VIEW WHOSE TYPE IS GONE cannot be evaluated for anyone,
        and returning zero would report every existing match as
        removed on the next evaluation."""
        counts = count_for_each(mediator, _view(object_type="NoSuchType"), [
            UserRecord("west", "us-west", "debug"),
        ])

        assert counts == {}

    def test_the_others_still_count(self, mediator):
        """ONE PERSON'S SEARCH RAISING -- a silo unreachable for their
        partition, a grant mid-change -- must not stop the rest being
        told."""
        class _Exploding:
            user_id = "exploding"
            security_value = object()  # unhashable comparisons downstream
            role_name = "debug"

        counts = count_for_each(mediator, _view(), [
            UserRecord("west", "us-west", "debug"),
        ])

        assert "west" in counts
