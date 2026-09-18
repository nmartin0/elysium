"""
An error message tells a caller nothing their grants do not.

IDEAS.md recorded this as unconfirmed: "Does any error message leak a
field name the acting user cannot read? Uniform denial is enforced on
DATA; error text is a separate surface and has never been audited as
one."

AUDITED, AND IT HOLDS. Filtering on a field the caller cannot read and
filtering on a field that does not exist produce the identical message
-- "Invalid search criteria" -- with no field name and no
distinguishing detail. A prober learns nothing about which fields a
type has.

These tests exist so the property stays true. It is the kind that
erodes: a future "more helpful" error naming the offending field would
look like a usability improvement and would be a disclosure.
"""

import pytest

from core.filters import parse_filters
from core.intermediate_layer.auth import UserRecord


def _condition(field):
    return parse_filters([{"field": field, "operator": "equals", "value": "x"}])


@pytest.fixture
def restricted(mediator):
    """A user who can read Customer but NOT Customer.email.

    Constructed rather than taken from the deployment, which happens
    not to declare such a role -- the property being tested is about
    the SHAPE of the permission, not about any deployment's choices.
    """
    base = dict(mediator.roles["customer_service"])
    base["allowed_actions"] = frozenset(
        action for action in base["allowed_actions"] if action != "read:Customer.email"
    )
    mediator.roles = {**mediator.roles, "no_email": base}
    return UserRecord("probe", "us-west", "no_email")


def test_the_field_is_genuinely_hidden_from_them(restricted, mediator):
    # The premise. Without this the tests below would pass trivially.
    visible = mediator.visible_schema(restricted)["Customer"]["fields"]

    assert "email" not in visible
    assert "name" in visible


def test_an_unreadable_field_and_a_missing_one_fail_identically(restricted, mediator):
    """Two different facts, one answer.

    If these differed, a caller could enumerate a type's real fields by
    filtering on guesses and sorting the errors.

    HONEST LIMIT, found by a control that did not fire. Both cases
    reach the SAME raise statement, so they are identical BY
    CONSTRUCTION rather than by two branches agreeing -- and a control
    changing that message changes both together, which this test cannot
    see.

    That construction is the real protection and it is stronger than a
    test: there is no second branch to drift. What this test does catch
    is the message being SPLIT in two later, which is the change that
    would actually introduce the leak. The test below catches the other
    one, a message that echoes the field back.
    """
    with pytest.raises(ValueError) as unreadable:
        mediator.search_object(restricted, "Customer", _condition("email"))

    with pytest.raises(ValueError) as missing:
        mediator.search_object(restricted, "Customer", _condition("no_such_field"))

    assert str(unreadable.value) == str(missing.value)


def test_neither_message_names_the_field(restricted, mediator):
    # The message could be identical and still leak, if it echoed back
    # whatever was asked for -- "Unknown field 'email'" is uniform
    # across both cases and still confirms the guess.
    for field in ("email", "no_such_field"):
        with pytest.raises(ValueError) as caught:
            mediator.search_object(restricted, "Customer", _condition(field))

        assert field not in str(caught.value)


def test_a_readable_field_still_works(restricted, mediator):
    # THE CONTROL. A search that refused everything would pass every
    # test above while making filtering useless.
    assert mediator.search_object(restricted, "Customer", _condition("name")) == []
