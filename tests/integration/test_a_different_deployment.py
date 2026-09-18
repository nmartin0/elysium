"""
Nothing in the product knows our ontology's nouns.

THE QUESTION THIS ANSWERS. Browse's columns, its filters, the charts,
the actions menu -- all are supposed to derive from the ontology, so a
different deployment reshapes them with no code change. "Supposed to"
was the whole of the evidence until this existed.

A SECOND FIXTURE SHARING NO NOUN WITH THE FIRST. Vessels and port
calls rather than customers and transactions; a security attribute
called `fleet` rather than `region`; a role called `fleet_ops`. Anything
that assumed a name fails here, and passing on the main fixture proves
nothing because that is the one everything was written against.

THE LINTER TAUGHT ME TWO RULES WHILE BUILDING IT, which is itself
evidence the rules are real and enforced rather than conventions:
security.via_field must name a LINK rather than a plain column, and
`write:` is not an enforced grant prefix -- writes are authorised per
action type.
"""

from pathlib import Path

import pytest

from core.deployment_loader import load_deployment

OTHER = Path(__file__).parent / "fixtures" / "other_deployment"


@pytest.fixture(scope="module")
def other():
    return load_deployment(OTHER)


def test_it_loads_at_all(other):
    # The floor. A deployment that cannot load proves nothing about
    # what derives from it.
    assert set(other.schema) == {"Vessel", "PortCall"}


def test_the_security_attribute_is_not_assumed_to_be_region(other):
    """OURS IS CALLED `fleet` HERE.

    A hardcoded "region" would survive every test against the main
    fixture and fail on the first real deployment that called it
    anything else.
    """
    assert other.security_attribute == "fleet"


def test_object_types_carry_their_own_fields(other):
    vessel = other.schema["Vessel"]["fields"]

    assert "vessel_name" in vessel
    assert "customer_id" not in vessel


def test_declared_display_names_survive(other):
    # The UI shows these instead of the raw column, so a deployment
    # that renames a field must see the new name.
    assert other.schema["Vessel"]["fields"]["vessel_name"]["display_name"] == "Vessel name"


def test_declared_precision_survives(other):
    # decimal_places is per-field ontology metadata, and a deployment
    # declaring 1 place must not inherit our 2.
    fields = other.schema["Vessel"]["fields"]

    assert fields["gross_tonnage"]["decimal_places"] == 1
    assert other.schema["PortCall"]["fields"]["berth_hours"]["decimal_places"] == 2


def test_the_action_takes_a_list_and_is_declared_here(other):
    # The bulk mechanism is ontology-driven, so a different deployment
    # gets it by declaring a list parameter -- not by us shipping one.
    action = other.action_types["ReassignFleet"]

    assert action["parameters"]["vessel_imos"]["type"] == "object_reference_list"
    assert "RecategorizeTransactions" not in other.action_types


def test_a_via_field_chain_works_with_different_names(other):
    """SECURITY THROUGH A LINK, which is the harder of the two forms.

    PortCall is secured through `vessel`, a link to Vessel, which is
    itself secured on `fleet`. If anything resolved that chain by the
    main fixture's names it would fail here.
    """
    port_call = other.schema["PortCall"]

    assert port_call["security"]["via_field"] == "vessel"
    assert other.schema["Vessel"]["security"]["field"] == "fleet"


def test_roles_are_this_deployment_s_own(other):
    assert "fleet_ops" in other.roles
    assert "customer_service" not in other.roles
