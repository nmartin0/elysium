"""
discover <= read, and the implication runs one way only.

THE PROBLEM THIS SOLVES. Grants were independent strings, so
`read:Customer.email` could be held WITHOUT `read:Customer` -- a role
authorised to read a field of a type it could not discover. Verified
against authorize() before the fix: True for the field, False for the
type. Nonsense that nothing prevented.

WHY NOT rwx. The rwx bits are INDEPENDENT by design, and that
independence is their defining property: `-w-` is a drop box for a
file. For a field it is incoherent -- setting a value on something you
cannot name. What is wanted here is MONOTONIC.

THE THREE STATES, per type and per field:

    (no grant)          it does not exist, as far as you are concerned
    discover:Customer   the type exists; no search, no ids, no fields
    read:Customer       enumerate it, get ids back

    discover:Customer.email   the field exists; the value is withheld
    read:Customer.email       the value

The middle rung on a TYPE was previously unreachable: the weakest grant
anyone could write already permitted enumeration, and an id is data.
"""

from core.intermediate_layer.auth import UserRecord, authorize

ROLES = {
    "reader": {"allowed_actions": frozenset(["read:Customer", "read:Customer.email"])},
    "spotter": {"allowed_actions": frozenset(["discover:Customer", "discover:Customer.email"])},
}
READER = UserRecord("r", "us-west", "reader")
SPOTTER = UserRecord("s", "us-west", "spotter")


def test_read_implies_discover_on_a_type():
    # Someone permitted to enumerate a type is necessarily permitted to
    # know it exists, so a deployment never writes both.
    assert authorize(READER, ROLES, "discover:Customer") is True


def test_read_implies_discover_on_a_field():
    assert authorize(READER, ROLES, "discover:Customer.email") is True


def test_discover_does_NOT_imply_read_on_a_type():
    # THE WHOLE POINT OF THE MIDDLE RUNG. If this were true there would
    # be two states, not three.
    assert authorize(SPOTTER, ROLES, "read:Customer") is False


def test_discover_does_NOT_imply_read_on_a_field():
    assert authorize(SPOTTER, ROLES, "read:Customer.email") is False


def test_a_discover_grant_answers_for_itself():
    assert authorize(SPOTTER, ROLES, "discover:Customer") is True
    assert authorize(SPOTTER, ROLES, "discover:Customer.email") is True


def test_the_implication_does_not_invent_grants_for_other_types():
    # THE CONTROL. An implication that answered yes too broadly would
    # pass every test above while granting the deployment away.
    assert authorize(READER, ROLES, "discover:Order") is False
    assert authorize(SPOTTER, ROLES, "discover:Order") is False


def test_an_unrelated_verb_is_unaffected():
    # execute:, manage:, tool: must keep matching exactly. The ladder
    # is about read and discover, and nothing else.
    roles = {"r": {"allowed_actions": frozenset(["execute:Rename"])}}
    user = UserRecord("u", "us-west", "r")

    assert authorize(user, roles, "execute:Rename") is True
    assert authorize(user, roles, "discover:Rename") is False
