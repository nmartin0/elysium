"""
Tests for schema-load validation of submission_criteria.

THE GAP THESE CLOSE: evaluate_submission_criteria() already rejects an
unknown check kind and an unknown operator, but only when a criterion
is actually REACHED -- at proposal time, on a real user's write, in a
running deployment. A deployment declaring `check: currentstate`
started cleanly, passed scripts/lint_deployment.py, and failed on the
first person to use that action.

The two call-site tests at the bottom are the ones that matter most.
validate_action_type_criteria() has to be CALLED by whatever loads a
deployment, because core/ontology/action_types.py may not import it --
they are siblings in core.ontology's layering. That makes it
forgettable in a way action_types.py's own checks are not, so each
caller gets a test that fails if the call is dropped.
"""

import pytest

from core.ontology.submission_criteria import (
    _OPERATORS,
    Criterion,
    OperatorName,
    validate_action_type_criteria,
)

VALID = {
    "description": "Ticket must be closed to reopen it",
    "check": "current_state",
    "field": "status",
    "operator": "equals",
    "value": "closed",
}


def _action_with(criterion: dict) -> dict:
    return {
        "ReopenTicket": {
            "affected_object_types": ["Ticket"],
            "sub_writes": [{
                "object_type": "Ticket",
                "object_id": "parameter.ticket_id",
                "operation": "update",
                "submission_criteria": [criterion],
                "mutations": [{"set": {"property": "status", "value": "open"}}],
            }],
        },
    }


def test_a_valid_criterion_is_accepted():
    # The control for every rejection test below: if this failed, they
    # would all pass for the wrong reason.
    validate_action_type_criteria(_action_with(VALID))


def test_a_misspelled_check_kind_is_rejected_at_load():
    # The original gap, verbatim. `currentstate` is the typo that used
    # to survive startup and the deployment linter.
    with pytest.raises(ValueError, match="currentstate"):
        validate_action_type_criteria(_action_with({**VALID, "check": "currentstate"}))


def test_a_misspelled_operator_is_rejected_at_load():
    with pytest.raises(ValueError, match="equalz"):
        validate_action_type_criteria(_action_with({**VALID, "operator": "equalz"}))


def test_a_missing_required_key_is_rejected():
    without_value = {k: v for k, v in VALID.items() if k != "value"}
    with pytest.raises(ValueError, match="value"):
        validate_action_type_criteria(_action_with(without_value))


def test_an_unknown_key_is_rejected_rather_than_ignored():
    # Silently dropping an unrecognised key is how a criterion ends up
    # meaning something other than it reads -- `feild` here would leave
    # the criterion checking nothing the author intended.
    with pytest.raises(ValueError, match="feild"):
        validate_action_type_criteria(_action_with({**VALID, "feild": "status"}))


def test_a_criterion_may_compare_against_a_non_string_value():
    # `value: Any` is deliberate, not laziness: criteria legitimately
    # compare against numbers, booleans and lists.
    for value in (10_000, True, ["open", "pending"]):
        validate_action_type_criteria(_action_with({**VALID, "value": value}))


def test_an_action_with_no_criteria_at_all_is_fine():
    action = _action_with(VALID)
    del action["ReopenTicket"]["sub_writes"][0]["submission_criteria"]
    validate_action_type_criteria(action)


def test_the_declared_vocabulary_and_the_dispatch_table_cannot_disagree():
    # OperatorName says what a schema may DECLARE; _OPERATORS says what
    # this module can EXECUTE. The module raises at import if they
    # diverge; this asserts the invariant it protects.
    from typing import get_args
    assert set(get_args(OperatorName)) == set(_OPERATORS)


def test_the_criterion_model_rejects_a_bad_check_directly():
    # Guards the model itself, not just the walker around it.
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Criterion.model_validate({**VALID, "check": "currentstate"})


def test_submission_criteria_declared_as_something_other_than_a_list_is_rejected():
    # A single mapping written where a list belongs -- the YAML mistake
    # of forgetting the leading "-". Caught before the per-criterion
    # loop, which would otherwise iterate the dict's KEYS and produce a
    # baffling error about the string "description".
    action = _action_with(VALID)
    action["ReopenTicket"]["sub_writes"][0]["submission_criteria"] = VALID

    with pytest.raises(ValueError, match="must be a list"):
        validate_action_type_criteria(action)
