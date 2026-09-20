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
def mediator():
    from core.deployment_loader import build_generation, resolve_runtime_paths

    paths = resolve_runtime_paths()
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
        from core.mirror.mirror_adapter import MirrorReadAdapter

        adapter = MirrorReadAdapter.__new__(MirrorReadAdapter)

        assert adapter._decimal_literal(
            "amount", "not a number", {"amount"},
        ) == "not a number"
