"""A pending write survives the types a source column produces
(SEC-16).

`to_row()` used plain `json.dumps` with no fallback, and
`expected_current_values` is READ FROM THE SOURCE. `field_types.py`
returns real `date` and `datetime` objects, and the shipped ontology
declares `decimal` for money -- with a comment explaining why it is
not `number` -- and `date` for `transaction_date`. Measured before
fixing:

    to_row(... {'amount': Decimal('49.99')})
    -> TypeError: Object of type Decimal is not JSON serializable

which fails the proposal with a 500 rather than a refusal. It did not
fire only because the one shipped action, RecategorizeTransactions,
writes `category`, a plain string.

WHY NOT `default=str`, WHICH IS THE OBVIOUS FIX AND IS WRONG.
`expected_current_values` is compared against a freshly READ value at
confirm -- the lost-update check. A stringified Decimal would never
equal the live Decimal, so every such write would be refused as a
conflict: a crash traded for a silently wrong answer, which is the
worse failure and the harder one to notice. The type has to travel
with the value, and `test_the_type_survives_not_just_the_text` below
is the test that says so.

THE SHAPE VERSION IS BUMPED TO 2, so a row written by this build is
REFUSED by an older one rather than misread -- an older build has no
decoder and would restore a tagged value as a plain dict. The cost is
that this build also refuses version 1 rows, dropping approvals
proposed in the fifteen minutes before an upgrade. That is this
module's own stated preference: "refusing rather than guessing at the
difference", and `UNREADABLE MEANS ABSENT` already makes it one lost
write rather than a lost queue.
"""

import datetime as dt
from decimal import Decimal

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite
from core.pending_write_serialisation import (
    UnreadablePendingWrite,
    UnstorablePendingWrite,
    from_row,
    to_row,
)


def _pending(expected: dict, parameters: dict | None = None) -> PendingWrite:
    return PendingWrite(
        sub_writes=(SubWrite("Transaction", "t1", "update", {"amount": 1}, expected),),
        user_id="alice",
        description="adjust t1",
        action_type_name="Adjust",
        origin="api",
        proposed_at=dt.datetime.now(dt.UTC),
        proposed_under_generation=1,
        parameters=parameters or {},
        proposer=UserRecord("alice", "us-west", "agent"),
    )


def _round_trip(expected: dict) -> dict:
    return from_row(to_row(_pending(expected))).sub_writes[0].expected_current_values


class TestTheTypesASourceColumnProduces:
    @pytest.mark.parametrize("value", [
        Decimal("49.99"),
        dt.date(2026, 1, 1),
        dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC),
        b"\x00\x01binary",
    ])
    def test_it_stores_and_restores(self, value):
        assert _round_trip({"field": value})["field"] == value

    @pytest.mark.parametrize("value", [
        Decimal("49.99"),
        dt.date(2026, 1, 1),
        dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC),
        b"\x00\x01binary",
    ])
    def test_the_type_survives_not_just_the_text(self, value):
        """THE POINT OF THE WHOLE CHANGE. `default=str` would pass the
        test above and fail this one -- and the confirm-time
        lost-update check compares against a freshly READ value, so a
        string where a Decimal belongs refuses every such write as a
        conflict."""
        restored = _round_trip({"field": value})["field"]

        assert type(restored) is type(value)

    def test_a_decimal_keeps_every_digit(self):
        """Never through float, for the reason the ontology already
        gives for choosing `decimal` over `number`."""
        exact = Decimal("12345678901234.56789")

        assert _round_trip({"amount": exact})["amount"] == exact

    def test_tagged_values_nested_in_dicts_and_lists(self):
        nested = {"outer": [{"inner": Decimal("1.5")}, dt.date(2026, 2, 3)]}

        assert _round_trip(nested) == nested

    def test_parameters_get_the_same_treatment(self):
        """Parameters are caller-supplied JSON today, but an
        object_reference_list resolved before storing is not."""
        pending = _pending({}, parameters={"cutoff": dt.date(2026, 5, 1)})

        assert from_row(to_row(pending)).parameters == {"cutoff": dt.date(2026, 5, 1)}


class TestWhatMustNotChange:
    def test_plain_json_values_are_untouched(self):
        plain = {"s": "x", "n": 3, "f": 1.5, "b": True, "z": None, "l": [1, 2]}

        assert _round_trip(plain) == plain

    def test_a_bool_does_not_become_an_int(self):
        """bool is a subclass of int, and the encoder checks it first."""
        assert type(_round_trip({"flag": True})["flag"]) is bool

    def test_the_rest_of_the_write_round_trips(self):
        pending = _pending({"amount": Decimal("1.00")})

        restored = from_row(to_row(pending))

        assert restored.user_id == pending.user_id
        assert restored.action_type_name == pending.action_type_name
        assert restored.proposed_under_generation == pending.proposed_under_generation
        assert restored.proposer == pending.proposer


class TestWhatIsRefusedRatherThanGuessedAt:
    def test_a_dict_holding_the_reserved_key(self):
        """It cannot be told apart from a tagged value on the way back,
        so storing it would corrupt it silently."""
        with pytest.raises(UnstorablePendingWrite, match="reserved key"):
            to_row(_pending({"weird": {"__elysium_type__": "decimal", "v": "1"}}))

    def test_a_type_with_no_encoding(self):
        with pytest.raises(UnstorablePendingWrite, match="cannot store"):
            to_row(_pending({"thing": object()}))

    def test_a_row_from_an_older_shape_version(self):
        """Version 1 rows have no tags and would decode correctly, and
        are refused anyway -- this module's stated preference is
        refusing over guessing, and UNREADABLE MEANS ABSENT makes it
        one lost write rather than a lost queue."""
        row = to_row(_pending({})).replace('"schema_version": 2', '"schema_version": 1')

        with pytest.raises(UnreadablePendingWrite, match="shape version"):
            from_row(row)

    def test_an_unknown_tagged_type(self):
        row = to_row(_pending({"x": Decimal("1")})).replace('"decimal"', '"quaternion"')

        with pytest.raises(UnreadablePendingWrite):
            from_row(row)
