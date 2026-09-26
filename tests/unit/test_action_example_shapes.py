"""An action's example shows the shape the parameter actually takes.

F-17: every action parameter was illustrated as `"name": "<value>"`,
a quoted string, whatever its declared type. Measuring what each type
costs made the fix much narrower than the finding, and the narrowing
is the interesting part.

SCALARS ARE FINE QUOTED. Nothing validates a parameter's declared type
-- propose_action() checks `required` and nothing else -- so the shape
the model copies is the shape that lands. But coerce() absorbs all of
it: "49.99" -> 49.99, "42" -> 42, "true" -> True, "2026-01-14" -> a
date. And JSON has no date type, so a date MUST be a string. Bare
<number> placeholders would buy nothing and risk the model emitting
the placeholder literally -- unparseable, where a quoted one is merely
imprecise.

A LIST SHOWN AS A STRING IS DIFFERENT IN KIND. The shipped deployment's
only action takes `transaction_ids (object_reference_list)` and was
illustrated as `"transaction_ids": "<value>"`. A model copying that
sends one string. write_mediator wraps a non-list in [value] rather
than iterating it, so the harm is bounded -- no character-by-character
walk -- but the proposal covers ONE object when the parameter exists
to carry many. Foundry calls an action using one a "bulk action type".
Ours was demonstrated in a form that cannot be bulk.

WORTH NOTING FOR BACKEND, not fixed here: a parameter's declared type
is never checked. `required` is validated at write_mediator.py:1209
and the type is not, anywhere. This change makes the model more likely
to send the right shape; it does not make the wrong shape impossible.
"""

from core.llm.agent_step_prompt import _describe_actions

BULK = {
    "RecategorizeTransactions": {
        "description": "Refile several transactions.",
        "parameters": {
            "transaction_ids": {
                "type": "object_reference_list",
                "object_type": "Transaction",
                "required": True,
            },
            "new_category": {"type": "string", "required": True},
        },
        "sub_writes": [{"object_type": "Transaction"}],
    }
}

SINGLE = {
    "ReopenTicket": {
        "description": "Reopen one ticket.",
        "parameters": {
            "ticket_id": {
                "type": "object_reference",
                "object_type": "Ticket",
                "required": True,
            },
            "amount": {"type": "number", "required": False},
        },
        "sub_writes": [{"object_type": "Ticket"}],
    }
}


def test_a_list_parameter_is_illustrated_as_a_list():
    rendered = _describe_actions(BULK)

    assert '"transaction_ids": ["<Transaction id>", "<Transaction id>"]' in rendered
    assert '"transaction_ids": "<value>"' not in rendered


def test_the_list_example_holds_more_than_one_entry():
    """A single-element list still reads as "put the id here".

    The parameter exists to carry several, and a bulk action
    demonstrated with one object is demonstrated wrong.
    """
    rendered = _describe_actions(BULK)

    assert rendered.count("<Transaction id>") >= 2


def test_a_single_reference_names_the_object_type_it_wants():
    """`"<value>"` does not say WHICH id.

    By the time an action is proposed the model is holding ids from
    several object types, and nothing in a bare placeholder says which
    belongs here -- the same gap AR-4 records for gathered results.
    """
    rendered = _describe_actions(SINGLE)

    assert '"ticket_id": "<Ticket id>"' in rendered


def test_scalar_parameters_are_deliberately_left_quoted():
    """THE HALF OF F-17 THAT WAS NOT WORTH CHANGING.

    Asserted rather than merely omitted, so that a later reading of
    the finding does not "finish the job" by turning these into bare
    placeholders. coerce() absorbs a quoted scalar; a model emitting a
    literal <number> produces unparseable JSON, which is strictly
    worse than a value that coerces.
    """
    rendered = _describe_actions(SINGLE)

    assert '"amount": "<value>"' in rendered


def test_the_declared_type_is_still_stated_in_prose():
    """The prose half was already right and must not be lost: the
    example shows shape, the prose gives the name and the type."""
    rendered = _describe_actions(BULK)

    assert "transaction_ids (object_reference_list, required)" in rendered
    assert "new_category (string, required)" in rendered
