"""
An unattended write may not take model-supplied values.

ROADMAP.md's security backlog: ontology data flows into `gathered`, and
`gathered` flows into the prompt, so a field value containing
instructions reaches the model as text. Three gates normally sit
between a model's decision and a write -- the execute grant, MAC per
sub_write per object, and a human at confirm. `auto_execute` removes
the third.

What remains is bounded by the acting user's own grants, so this is not
privilege escalation. It is ACTION WITHOUT CONSENT, a different
property and one this project takes seriously.

THE DISTINCTION THAT IS STATICALLY DETECTABLE. A mutation whose value
is `parameter.<name>` is chosen BY THE MODEL, so with auto_execute
injected text decides both WHETHER to write and WHAT to write. A
literal lets it decide only whether -- a far smaller blast radius.

ROADMAP.md also proposed requiring a submission criterion instead. That
is weaker: a criterion can be written vacuously true, so it would force
an author to type something without forcing them to think. And its
third proposal -- "no field the model has read" -- is not knowable at
validation time, since what a model has read is a property of a running
query rather than of a schema.
"""

import pytest

from core.ontology.action_types import validate_action_types

SCHEMA = {
    "Ticket": {
        "id_field": "ticket_id",
        "fields": {"state": {"data_type": "string"}, "note": {"data_type": "string"}},
    }
}


def _action(mutations, auto_execute=None):
    # PARAMETERS ARE DERIVED FROM THE MUTATIONS, because a separate
    # validator refuses a parameter that is declared and never
    # referenced -- and a fixture declaring new_state for the
    # literal-value case tripped it. Deriving them keeps each case
    # testing the auto_execute guard rather than that one.
    referenced = {
        mutation["set"]["value"].split(".", 1)[1]
        for mutation in mutations
        if str(mutation["set"]["value"]).startswith("parameter.")
    }
    parameters = {
        "ticket_id": {"type": "object_reference", "object_type": "Ticket",
                      "required": True},
    }
    for name in referenced:
        parameters[name] = {"type": "string", "required": True}

    action = {
        "affected_object_types": ["Ticket"],
        "parameters": parameters,
        "sub_writes": [{
            "object_type": "Ticket",
            "object_id": "parameter.ticket_id",
            "operation": "update",
            "mutations": mutations,
        }],
    }
    if auto_execute is not None:
        action["auto_execute"] = auto_execute
    return {"CloseTicket": action}


LITERAL = [{"set": {"property": "state", "value": "closed"}}]
FROM_MODEL = [{"set": {"property": "state", "value": "parameter.new_state"}}]


def test_auto_execute_with_a_model_supplied_value_is_refused():
    # THE CASE THIS EXISTS FOR. The model chooses whether AND what,
    # with no human in between.
    with pytest.raises(ValueError, match="model-supplied values"):
        validate_action_types(_action(FROM_MODEL, auto_execute=True), SCHEMA)


def test_the_message_names_the_offending_field():
    # An action can have many mutations. "Something is wrong" would
    # leave an author reading every one of them.
    with pytest.raises(ValueError, match=r"\['state'\]"):
        validate_action_types(_action(FROM_MODEL, auto_execute=True), SCHEMA)


def test_auto_execute_with_literal_values_is_allowed():
    # THE POINT OF THE DISTINCTION. Foundry's own Action tool "can be
    # configured to run automatically", and a deployment should be able
    # to let an agent file a low-stakes note unattended. Refusing every
    # auto_execute would make the flag useless rather than safe.
    validate_action_types(_action(LITERAL, auto_execute=True), SCHEMA)


def test_a_model_supplied_value_is_fine_WITHOUT_auto_execute():
    # THE CONTROL, and the overwhelmingly common case -- every action
    # in the shipped deployment takes a parameter. A guard that refused
    # these would break the product while claiming to secure it.
    validate_action_types(_action(FROM_MODEL), SCHEMA)
    validate_action_types(_action(FROM_MODEL, auto_execute=False), SCHEMA)


def test_the_boolean_check_still_applies():
    with pytest.raises(ValueError, match="must be true or false"):
        validate_action_types(_action(LITERAL, auto_execute="yes"), SCHEMA)


def test_a_user_reference_is_not_model_supplied():
    # `user.security_value` is substituted by Python from the acting
    # user's record and is NEVER model-supplied -- that is the whole
    # reason it exists rather than passing a parameter. It must not be
    # caught by this guard.
    mutations = [{"set": {"property": "note", "value": "user.security_value"}}]

    validate_action_types(_action(mutations, auto_execute=True), SCHEMA)
