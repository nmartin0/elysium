"""A caller-supplied parameter may not choose an object's compartment
(SEC-27).

THE HAZARD WAS ALREADY NAMED, in `_resolve_mutation_value`'s own
comment: a `parameter.<n>` reference for the security field "would let
the model (or a hallucinated/injected value) choose ANY security
value, including one that doesn't belong to the user actually
authorized to perform this action."

Nothing refused it. Measured -- this loaded fine:

    mutations:
      - set: {property: region, value: parameter.target_region}

WHY IT IS A MAC HOLE RATHER THAN A SCHEMA AUTHOR'S MISTAKE. The model
composes an action's parameter values, and the model is untrusted by
this project's first principle. So the compartment of a newly created
object would be chosen by the least trusted component in the system --
possibly one the acting user cannot see into at all.

AND NOTHING ELSE CATCHES IT. `_authorize_sub_write` skips MAC for a
create, correctly, because there is no row yet to consult.
`_refuse_cross_compartment` excludes creates from its write set for
the same reason. Both exclusions are right on their own, and together
they leave the create path with no compartment check at all.

A LITERAL IS ALLOWED, AND I FIRST REFUSED IT. An existing test failed
-- a create setting `region: "us-west"` for a us-west user -- and
reading it settled the point: Elysium is SINGLE-TENANT, so a
compartment in a schema is a region inside one org, chosen by the
author at authoring time. That is trusted configuration. The hazard is
the CALLER's value, not the author's, and conflating them was my
mistake. The suite caught it, which is the third time on this branch
that the full tier corrected a premise my own targeted tests endorsed.
"""

import pytest

from core.ontology.write_mediator import WriteMediator

SCHEMA = {"Customer": {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "fields": {"customer_id": {"type": "data"}, "region": {"type": "data"},
               "name": {"type": "data"}},
}}


class _Mediator:
    def _type_schema(self, object_type):
        return SCHEMA.get(object_type)


def _write_mediator() -> WriteMediator:
    mediator = object.__new__(WriteMediator)
    mediator._adapter_mediator = _Mediator()
    return mediator


@pytest.fixture
def mediator():
    return _write_mediator()


def _check(mediator, field, value):
    mediator._refuse_a_chosen_compartment("Customer", field, value, "MakeCustomer")


class TestTheCallerMayNotChooseACompartment:
    def test_a_parameter_reference_is_refused(self, mediator):
        with pytest.raises(PermissionError, match="may not choose a compartment"):
            _check(mediator, "region", "parameter.target_region")

    def test_the_refusal_names_the_field_and_what_to_use(self, mediator):
        """A schema author has to be able to fix it from the message."""
        with pytest.raises(PermissionError) as raised:
            _check(mediator, "region", "parameter.target_region")

        message = str(raised.value)
        assert "Customer.region" in message
        assert "user.security_value" in message

    def test_any_parameter_name_is_refused(self, mediator):
        with pytest.raises(PermissionError):
            _check(mediator, "region", "parameter.anything_at_all")


class TestWhatMustStillBeAllowed:
    """THE OPPOSITE DIRECTION. A check that refused every mutation
    would make creates impossible, and creates are the only way an
    object's security field can ever be populated."""

    def test_user_security_value_is_the_intended_form(self, mediator):
        _check(mediator, "region", "user.security_value")

    def test_a_literal_the_author_chose_is_allowed(self, mediator):
        """Single-tenant: a compartment in a schema is a region inside
        one org, picked at authoring time. This is the case that
        failed when I first refused literals too."""
        _check(mediator, "region", "us-west")

    def test_an_ordinary_field_may_come_from_a_parameter(self, mediator):
        """Only the SECURITY field is restricted. Every other field
        taking a caller-supplied value is the normal case and the
        reason actions have parameters at all."""
        _check(mediator, "name", "parameter.new_name")

    def test_a_type_whose_security_is_via_field_has_no_field_to_guard(self, mediator):
        """`security.via_field` reaches the compartment through a link,
        so no mutation on this type can set it directly."""
        _check(mediator, "customer_id", "parameter.new_id")

    def test_an_unknown_object_type_does_not_crash(self, mediator):
        """A type the schema does not describe is somebody else's
        error to report, not this guard's to raise badly."""
        mediator._refuse_a_chosen_compartment(
            "NoSuchType", "region", "parameter.x", "MakeCustomer")
