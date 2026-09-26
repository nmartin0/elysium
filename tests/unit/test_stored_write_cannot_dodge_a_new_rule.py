"""A stored write is not waved through a rule it cannot answer
(001's F-08).

WHAT F-08 SAID: submission_criteria's parameter-skip is safe only via
an unstated precondition. Write the precondition down, or enforce it.

WHAT THE PRECONDITION IS. A "parameter" criterion is silently SKIPPED
when its field is absent from the call's parameters. At PROPOSE time
that is correct and required-ness makes it safe: propose_action()
validates every required parameter ("Missing required parameter ...")
BEFORE any criterion is evaluated, so a rule guarding a required
parameter can never be dodged by omitting it. Nothing states that the
ordering is load-bearing, and it was moved to its current position for
an unrelated reason.

WHERE THE PRECONDITION DOES NOT HOLD, and this is the part no report
raised. At CONFIRM the two halves come from different moments:
_criteria_for() deliberately reads the CURRENT action definition --
"a write proposed before a four-eyes rule was added must still obey
it" -- while pending.parameters was captured under the definition in
force when the write was proposed. REPRODUCED before fixing, against
evaluate_submission_criteria directly:

    stored parameters : {'employee_id': 'e1'}
    new rule          : amount less_than 1000
    verdict           : PASSED -- the new rule was silently skipped

    the same rule with 'amount' supplied -> correctly refused

So the rule is skipped precisely BECAUSE the write predates it, which
is the opposite of what _criteria_for promises.

THE FIX IS NARROW. Only a parameter the CURRENT definition declares
`required: true` can be absent for this reason. An optional parameter
being absent is the legitimate case the skip exists for, and is
indistinguishable from it -- widening the refusal would start
inventing violations on writes that are perfectly fine.
"""

import pytest

from core.ontology.write_mediator import WriteMediator


def _mediator(action_types: dict) -> WriteMediator:
    mediator = object.__new__(WriteMediator)
    mediator.action_types = action_types
    return mediator


class _Pending:
    """Only what _refuse_criteria_this_write_cannot_answer reads."""

    def __init__(self, parameters: dict, action_type_name: str = "RaiseLimit"):
        self.parameters = parameters
        self.action_type_name = action_type_name


AMOUNT_RULE = [{
    "description": "Amount must be under 1000",
    "check": "parameter", "field": "amount",
    "operator": "less_than", "value": 1000,
}]


def _declared(**params) -> dict:
    return {"RaiseLimit": {"parameters": params}}


class TestARuleTheStoredWriteCannotAnswer:
    def test_a_newly_required_parameter_refuses_the_write(self):
        """THE DEFECT. The rule is about a parameter that is required
        today and absent from a write proposed before it was."""
        mediator = _mediator(_declared(amount={"type": "number", "required": True}))
        pending = _Pending({"employee_id": "e1"})

        with pytest.raises(ValueError, match="proposed before"):
            mediator._refuse_criteria_this_write_cannot_answer(pending, AMOUNT_RULE)

    def test_and_the_message_says_what_to_do(self):
        """A refusal nobody can act on becomes a support ticket."""
        mediator = _mediator(_declared(amount={"type": "number", "required": True}))

        with pytest.raises(ValueError) as raised:
            mediator._refuse_criteria_this_write_cannot_answer(
                _Pending({"employee_id": "e1"}), AMOUNT_RULE,
            )

        message = str(raised.value)
        assert "'amount'" in message
        assert "Re-propose the action." in message


class TestWhatMustStillGetThrough:
    """THE OPPOSITE DIRECTION, and it is most of the surface. A guard
    that refused whenever a parameter was absent would break every
    action with an optional one."""

    def test_an_optional_parameter_absent_is_the_legitimate_skip(self):
        mediator = _mediator(_declared(amount={"type": "number"}))

        mediator._refuse_criteria_this_write_cannot_answer(
            _Pending({"employee_id": "e1"}), AMOUNT_RULE,
        )

    def test_a_parameter_that_is_present_is_fine(self):
        """Present means evaluate_submission_criteria can judge it --
        this guard's job is only to spot what it CANNOT judge."""
        mediator = _mediator(_declared(amount={"type": "number", "required": True}))

        mediator._refuse_criteria_this_write_cannot_answer(
            _Pending({"employee_id": "e1", "amount": 50}), AMOUNT_RULE,
        )

    def test_a_current_state_criterion_is_not_this_guard_s_business(self):
        """Only `parameter` criteria can be dodged by absence. A
        current_state rule reads the object, which is always there."""
        mediator = _mediator(_declared(amount={"type": "number", "required": True}))
        state_rule = [{
            "description": "Ticket must be closed", "check": "current_state",
            "field": "status", "operator": "equals", "value": "closed",
        }]

        mediator._refuse_criteria_this_write_cannot_answer(
            _Pending({"employee_id": "e1"}), state_rule,
        )

    def test_an_action_declaring_no_parameters_does_not_crash(self):
        """A criterion naming a parameter the definition no longer
        declares at all: not required, so not this guard's case. F-14
        covers load-time validation of that."""
        mediator = _mediator({"RaiseLimit": {}})

        mediator._refuse_criteria_this_write_cannot_answer(
            _Pending({"employee_id": "e1"}), AMOUNT_RULE,
        )

    def test_no_criteria_is_a_no_op(self):
        mediator = _mediator(_declared(amount={"type": "number", "required": True}))

        mediator._refuse_criteria_this_write_cannot_answer(_Pending({}), [])
