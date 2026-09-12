"""
A pending write describes itself in a sentence, not a repr.

This was `f"{name}(parameters={parameters})"`, which was fine as a log
line and became the primary text of an inbox row the moment
/writes/awaiting existed. In a real queue it read:

    RecategorizeTransaction(parameters={'transaction_id': 1,
    'new_category': 'travel'})

Python punctuation a reviewer has to parse before they can begin
thinking about the decision.

BUILT FROM WHAT THE DEPLOYMENT ALREADY AUTHORED. Action types carry a
`description` written for humans and parameters carry `display_name`;
both existed in deployment/etc and neither was used here.
"""

from core.ontology.write_mediator import _describe_action

ACTION = {
    "description": "Change which category a transaction is filed under.",
    "parameters": {
        "transaction_id": {"type": "object_reference"},
        "new_category": {"type": "string", "display_name": "New category"},
    },
}


def test_uses_the_authored_sentence():
    described = _describe_action("RecategorizeTransaction", ACTION, {})

    assert described == "Change which category a transaction is filed under."


def test_uses_a_parameters_display_name_where_one_is_declared():
    described = _describe_action(
        "RecategorizeTransaction", ACTION, {"new_category": "travel"},
    )

    assert "New category: travel" in described


def test_falls_back_to_the_raw_name_rather_than_dropping_a_parameter():
    # LOSES NOTHING THE OLD FORM CARRIED, which matters because this
    # string reaches the audit log -- a prettier description that
    # dropped an unlabelled parameter would be a quieter audit trail
    # bought with readability.
    described = _describe_action(
        "RecategorizeTransaction", ACTION, {"transaction_id": 1},
    )

    assert "transaction_id: 1" in described


def test_every_parameter_appears():
    described = _describe_action(
        "RecategorizeTransaction", ACTION,
        {"transaction_id": 1, "new_category": "travel"},
    )

    assert "1" in described
    assert "travel" in described


def test_falls_back_to_the_action_name_when_nothing_is_authored():
    # An action type with no description is legal, and a row reading
    # nothing at all would be worse than a bare name.
    described = _describe_action("SomeAction", {"parameters": {}}, {"x": 1})

    assert described.startswith("SomeAction")
    assert "x: 1" in described


def test_an_action_with_no_parameters_reads_as_a_plain_sentence():
    # No trailing empty parentheses -- the punctuation only earns its
    # place when it has something to hold.
    described = _describe_action("RecategorizeTransaction", ACTION, {})

    assert "(" not in described


def test_it_is_not_a_python_repr():
    # THE REGRESSION THIS GUARDS. The old form is what a dict renders
    # as, and it is what this would silently become again if someone
    # "simplified" the builder back to an f-string.
    described = _describe_action(
        "RecategorizeTransaction", ACTION,
        {"transaction_id": 1, "new_category": "travel"},
    )

    assert "parameters=" not in described
    assert "{" not in described
    assert "'" not in described
