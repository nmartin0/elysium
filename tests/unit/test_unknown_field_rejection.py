"""
A field name the type does not have, refused with the names it does.

MEASURED, NOT IMAGINED. Asked for one customer's transactions, a real
model (phi4-mini) asked for `field_names: ["*"]` -- a wildcard that
does not exist here and that it had no way to know was wrong.

get_field returns None for an unknown field, so the step SUCCEEDED and
returned `{"*": None}`: indistinguishable from a field that is
genuinely empty. The agent asked again, and again, until the duplicate
guard stopped it nine hops later, 814 seconds in.

THE MEDIATOR MUST NOT CHANGE, and that is the constraint that decides
where this lives. get_field returns None for both "no such field" and
"not authorised", deliberately, so an unauthorised caller cannot map
the schema by guessing names. Raising there would leak exactly what
that hides.

THE LOOP CAN SAY IT SAFELY, because visible_schema is already filtered
to what THIS user may see.
"""

import pytest

from core.agent.agentic_loop import AgentLoop

SCHEMA = {
    "Transaction": {"fields": {"amount": {}, "category": {}, "currency": {}}},
}


def _reject(field_names, object_type="Transaction"):
    AgentLoop._reject_unknown_fields(
        {"object_type": object_type, "field_names": field_names}, SCHEMA,
    )


class TestRejection:
    def test_the_wildcard_a_real_model_invented_is_refused(self):
        with pytest.raises(ValueError, match=r"no field\(s\) '\*'"):
            _reject(["*"])

    def test_it_names_the_fields_that_do_exist(self):
        """"Unknown field" ALONE LEAVES THE MODEL GUESSING AGAIN, which
        is how this started. The message has to end the guessing."""
        with pytest.raises(ValueError, match="amount, category, currency"):
            _reject(["*"])

    def test_it_says_there_is_no_wildcard(self):
        # The specific wrong belief, addressed directly. A model that
        # tried "*" will try "all" next unless told.
        with pytest.raises(ValueError, match="no wildcard"):
            _reject(["*"])

    def test_one_bad_name_among_good_ones_is_refused(self):
        with pytest.raises(ValueError, match="'nope'"):
            _reject(["amount", "nope"])

    def test_every_bad_name_is_listed_at_once(self):
        # One round trip per wrong name would cost four minutes each on
        # the model this was measured against.
        with pytest.raises(ValueError, match="'a', 'b'"):
            _reject(["a", "b"])


class TestAcceptance:
    def test_real_fields_pass(self):
        # THE CONTROL. A check that refused everything would stop the
        # agent entirely, and the symptom -- no answers -- looks like a
        # model problem rather than a guard problem.
        _reject(["amount", "category"])

    def test_no_field_names_is_not_this_check_s_business(self):
        _reject([])

    def test_an_unknown_object_type_is_left_alone(self):
        """NOT OUR FAULT TO REPORT. An unknown object_type has its own
        handling further in, and duplicating it here would give two
        different messages for one mistake."""
        _reject(["anything"], object_type="NoSuchType")

    def test_a_type_the_user_cannot_see_is_left_alone(self):
        # visible_schema is already MAC-filtered, so a type missing
        # from it is a permission outcome, not a typo -- and saying
        # "no such field on X" would confirm X exists.
        _reject(["amount"], object_type="Secret")
