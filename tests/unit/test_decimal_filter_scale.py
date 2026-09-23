"""
Filtering a decimal field uses the scale the data is stored at.

THE BUG, MEASURED: `amount == 49.99` against the mirror raised "could
not convert 49.99 into a decimal(38, 9), scales differ 9 <> 2".
PyIceberg refuses a scale mismatch rather than widening, so a person
filtering on a price had to type NINE DECIMAL PLACES or get an error
naming a storage detail they never chose.

FOUND BY A TEST OF THE TRIGGER EVALUATOR, not by the decimal work
that introduced it. The live read path coerces on READ and nothing
coerced on FILTER -- the two halves were built weeks apart and only
met when a saved view tried to filter one.

THE SCALE COMES FROM THE TABLE, not the ontology. What matters is
what the data is stored at, and this adapter reads the table anyway.
"""

import pytest

from core.filters import FieldFilter
from core.intermediate_layer.auth import UserRecord


@pytest.fixture
def mediator(synced_deployment):
    from core.deployment_loader import build_generation

    # E-08: a deployment of its own, not the developer's.
    paths = synced_deployment
    return build_generation(
        paths.config_dir, paths.data_dir, paths.log_dir,
    ).mediator


@pytest.fixture
def user():
    return UserRecord("west", "us-west", "debug")


def _amount_equals(mediator, user, value):
    return mediator.search_object(
        user, "Transaction",
        [FieldFilter(field="amount", operator="equals", value=value)],
    )


class TestAHumanScaleValueWorks:
    def test_two_decimal_places_match(self, mediator, user):
        """THE CASE THAT FAILED. A price is written with two decimal
        places by everybody who has ever written one."""
        assert len(_amount_equals(mediator, user, "49.99")) > 0

    def test_the_storage_scale_still_works(self, mediator, user):
        """NOT A REPLACEMENT. A value already at the stored scale must
        keep matching -- otherwise the fix trades one broken input for
        another."""
        assert len(_amount_equals(mediator, user, "49.990000000")) > 0

    def test_both_give_the_same_answer(self, mediator, user):
        assert (
            len(_amount_equals(mediator, user, "49.99"))
            == len(_amount_equals(mediator, user, "49.990000000"))
        )


class TestItDoesNotMatchWhatItShouldNot:
    def test_a_different_value_matches_nothing(self, mediator, user):
        """QUANTIZING MUST NOT WIDEN. A fix that made every decimal
        filter match would pass every test above."""
        assert _amount_equals(mediator, user, "0.01") == []


class TestNonDecimalFieldsAreUntouched:
    def test_a_string_filter_still_works(self, mediator, user):
        """THE GUARD IS BELT-AND-BRACES FOR MOST VALUES, and this test
        says so rather than overclaiming.

        A control quantizing EVERY field passes: `Decimal("us-west")`
        raises InvalidOperation and the value passes through unchanged,
        so a non-numeric filter is unaffected either way.

        WHERE THE GUARD ACTUALLY BITES is a TEXT column holding a
        numeric-looking string -- "49.99" in a text field would become
        "49.990000000" and match nothing. The shipped fixture has no
        such column, so that case is reasoned about rather than
        exercised, which is worth saying out loud.
        """
        matched = mediator.search_object(
            user, "Customer",
            [FieldFilter(field="region", operator="equals", value="us-west")],
        )

        assert len(matched) > 0

    def test_an_unparseable_value_passes_through(self):
        """SOMEBODY ELSE'S ERROR TO REPORT. Swallowing it here would
        turn a clear message into an empty result."""
        from core.mirror.iceberg_reader import IcebergNamespaceReader

        # The mechanics moved to the shared reader (GOLD-3).
        adapter = IcebergNamespaceReader.__new__(IcebergNamespaceReader)

        assert adapter._decimal_literal(
            "amount", "not a number", {"amount"},
        ) == "not a number"


class TestEveryOperatorThatCarriesALiteral:
    """001's F-20: only `equals` was fixed. `in` and `not_in` still sent
    str(value), so pyiceberg refused the literal outright -- reproduced
    on the shipped deployment, `amount equals 49.99` returning rows
    while `amount in [49.99]` raised. A chart's "keep" cross-filter IS
    an `in`, so clicking a bar on a money chart was an error."""

    def _search(self, mediator, user, operator, value):
        return mediator.search_object(
            user, "Transaction",
            [FieldFilter(field="amount", operator=operator, value=value)],
        )

    def test_in_matches_what_equals_matches(self, mediator, user):
        equal = _amount_equals(mediator, user, "49.99")

        assert self._search(mediator, user, "in", ["49.99"]) == equal

    def test_in_at_the_storage_scale_agrees_too(self, mediator, user):
        assert (self._search(mediator, user, "in", ["49.990000000"])
                == self._search(mediator, user, "in", ["49.99"]))

    def test_not_in_is_the_complement_of_in(self, mediator, user):
        everything = mediator.search_object(user, "Transaction", [])
        matched = self._search(mediator, user, "in", ["49.99"])

        excluded = self._search(mediator, user, "not_in", ["49.99"])

        assert sorted(excluded + matched) == sorted(everything)

    def test_several_values_at_human_scale(self, mediator, user):
        both = self._search(mediator, user, "in", ["49.99", "120.50"])

        assert len(both) >= len(self._search(mediator, user, "in", ["49.99"]))

    def test_a_string_column_is_unaffected(self, mediator, user):
        """_decimal_literal quantises only decimal columns; everything
        else keeps the behaviour it had."""
        west = mediator.search_object(
            user, "Customer",
            [FieldFilter(field="region", operator="in", value=["us-west"])],
        )

        assert west == mediator.search_object(
            user, "Customer",
            [FieldFilter(field="region", operator="equals", value="us-west")],
        )


class TestTheRangeBounds:
    """NOT REACHABLE TODAY: validate_filter declines `range` on a decimal
    field, which is the roadmap's open question about filtering money by
    amount. The operator is made correct before that question is
    answered -- and pinned here, since nothing else exercises it."""

    def _term(self, value, decimal_columns=frozenset({"amount"})):
        from core.mirror.iceberg_reader import IcebergNamespaceReader
        # The mechanics moved to the shared reader (GOLD-3).
        adapter = IcebergNamespaceReader.__new__(IcebergNamespaceReader)
        return adapter._term_for(
            FieldFilter(field="amount", operator="range", value=value), set(decimal_columns),
        )

    def test_a_bound_is_quantised_to_the_storage_scale(self):
        term = self._term({"min": 10})

        assert str(term.literal.value) == "10.000000000"

    def test_both_bounds_are(self):
        term = self._term({"min": 10, "max": 50})

        assert [str(bound.literal.value) for bound in (term.left, term.right)] \
            == ["10.000000000", "50.000000000"]

    def test_a_column_that_is_not_a_decimal_is_left_alone(self):
        term = self._term({"min": 10}, decimal_columns=frozenset())

        assert str(term.literal.value) == "10"
