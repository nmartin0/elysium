"""
Tests for `check: user` submission criteria -- the acting principal as
a third thing a criterion can read, beside object state and call
parameters.

Follows Palantir Foundry's Current User template, which checks "a
user's ID, group memberships via group IDs, or any other multipass
attribute available". All three UserRecord fields are allowed for that
reason, including role_name, which overlaps with what an execute:
grant already says. See core/ontology/submission_criteria.py for why
that overlap was accepted rather than designed out.

The end-to-end test at the bottom is the one that matters most. Every
test above it calls evaluate_submission_criteria() directly, which
proves the function works and NOT that WriteMediator passes it a real
user -- twice this session a test has passed while exercising the
wrong layer.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.submission_criteria import (
    SubmissionCriteriaViolation,
    UserField,
    validate_action_type_criteria,
)
from core.ontology.submission_criteria import evaluate_submission_criteria as evaluate

ALICE = UserRecord("alice", "us-west", "lead")


def _criterion(field: str, operator: str = "equals", value: object = "alice") -> dict:
    return {
        "description": f"user.{field} must be {value!r}",
        "check": "user", "field": field, "operator": operator, "value": value,
    }


@pytest.mark.parametrize("field,value", [
    ("user_id", "alice"),
    ("security_value", "us-west"),
    ("role_name", "lead"),
])
def test_a_user_criterion_passes_when_the_attribute_matches(field, value):
    evaluate([_criterion(field, value=value)], None, {}, ALICE)


@pytest.mark.parametrize("field,value", [
    ("user_id", "bob"),
    ("security_value", "us-east"),
    ("role_name", "auditor"),
])
def test_a_user_criterion_denies_when_the_attribute_does_not_match(field, value):
    with pytest.raises(SubmissionCriteriaViolation):
        evaluate([_criterion(field, value=value)], None, {}, ALICE)


def test_a_user_criterion_supports_membership_in_a_static_list():
    # Foundry's documented static-list case: user IDs compared against
    # a statically defined list. This is what naming individuals looks
    # like, and nothing in RBAC or MAC can express it.
    allowed = _criterion("user_id", operator="in", value=["alice", "carol"])
    evaluate([allowed], None, {}, ALICE)
    with pytest.raises(SubmissionCriteriaViolation):
        evaluate([allowed], None, {}, UserRecord("mallory", "us-west", "lead"))


def test_a_user_criterion_applies_on_a_create_where_current_state_would_skip():
    # THE NEVER-SKIPS PROPERTY. A current_state criterion skips on
    # create because no prior object exists; a user criterion has no
    # such excuse, because there is always an acting user. current_
    # state=None here is exactly what propose_action() passes for a
    # create -- if "user" skipped alongside it, this would not raise.
    with pytest.raises(SubmissionCriteriaViolation):
        evaluate([_criterion("user_id", value="bob")], None, {}, ALICE)


def test_an_unset_attribute_denies_rather_than_passes():
    # security_value and role_name are Optional on UserRecord. A user
    # with neither compares as None and FAILS -- the fail-safe
    # direction. Skipping instead would silently let an unconfigured
    # user past a rule written to constrain them.
    nobody = UserRecord("nobody", None, None)
    with pytest.raises(SubmissionCriteriaViolation):
        evaluate([_criterion("role_name", value="lead")], None, {}, nobody)
    with pytest.raises(SubmissionCriteriaViolation):
        evaluate([_criterion("security_value", value="us-west")], None, {}, nobody)


def test_evaluating_a_user_criterion_without_an_acting_user_refuses_outright():
    # The backstop for a caller that neither supplies a user nor
    # filters user criteria out. Guessing -- skip? deny? -- would
    # either weaken a real rule or invent a violation.
    with pytest.raises(ValueError, match="without an acting user"):
        evaluate([_criterion("user_id")], None, {}, None)


def test_a_user_criterion_naming_an_unknown_attribute_is_rejected_at_load():
    # Not at proposal time, where it would be an AttributeError on a
    # real user's write. `field` cannot be a Literal for every check
    # kind -- object fields and parameter names are open sets -- but
    # for "user" it is closed.
    action = {"A": {"sub_writes": [{
        "object_type": "T", "object_id": "parameter.x", "operation": "update",
        "submission_criteria": [_criterion("email")],
        "mutations": [{"set": {"property": "p", "value": "v"}}],
    }]}}
    with pytest.raises(ValueError, match="email"):
        validate_action_type_criteria(action)


def test_every_declared_user_field_is_a_real_userrecord_attribute():
    # The invariant the module raises on at import: UserField says what
    # a schema may read, UserRecord says what exists. A rename on one
    # side would otherwise validate at load and fail at proposal time.
    from typing import get_args
    for field in get_args(UserField):
        assert hasattr(ALICE, field)


# --- The wiring, and the prompt builder ---

from core.llm.agent_step_prompt import _sub_write_validity_for_object  # noqa: E402
from tests.unit.test_named_actions import _record, write_mediator  # noqa: E402,F401

_USER_GATED_ACTION = {
    "affected_object_types": ["Ticket"],
    "parameters": {"ticket_id": {"type": "object_reference", "object_type": "Ticket", "required": True}},
    "sub_writes": [{
        "object_type": "Ticket",
        "object_id": "parameter.ticket_id",
        "operation": "update",
        "submission_criteria": [{
            "description": "Only carol may escalate a ticket",
            "check": "user", "field": "user_id", "operator": "equals", "value": "carol",
        }],
        "mutations": [{"set": {"property": "status", "value": "escalated"}}],
    }],
}


def test_propose_action_really_passes_the_acting_user_to_the_criteria(write_mediator):  # noqa: F811
    # THE WIRING TEST. Every test above calls evaluate() directly and
    # would pass even if WriteMediator never supplied a UserRecord at
    # all. This goes through the real propose_action() path: "lead" is
    # not "carol", so the criterion must deny.
    write_mediator.action_types["EscalateTicket"] = _USER_GATED_ACTION
    write_mediator.roles["support_lead"]["allowed_actions"].append("execute:EscalateTicket")

    with pytest.raises(SubmissionCriteriaViolation, match="carol"):
        write_mediator.propose_action(_record("lead"), "EscalateTicket",
                                      {"ticket_id": "t1"}, origin="human")


def test_the_prompt_builder_gives_no_verdict_on_a_user_criterion():
    # Prompt construction has no UserRecord, deliberately -- a user's
    # identity must not shape what the model is told. So it abstains
    # rather than guessing.
    assert _sub_write_validity_for_object(_USER_GATED_ACTION["sub_writes"][0], {}) is None


def test_the_prompt_builder_still_gives_verdicts_on_state_criteria():
    # THE CONTROL for the test above. Without this, that None could be
    # the pre-existing "known_state is missing a needed field" path
    # rather than the user filter, and the filter could be deleted with
    # nothing noticing.
    state_gated = {
        "object_type": "Ticket", "object_id": "parameter.ticket_id", "operation": "update",
        "submission_criteria": [{
            "description": "Ticket must be closed", "check": "current_state",
            "field": "status", "operator": "equals", "value": "closed",
        }],
        "mutations": [{"set": {"property": "status", "value": "open"}}],
    }
    assert _sub_write_validity_for_object(state_gated, {"status": "closed"}) == (True, "")
    verdict = _sub_write_validity_for_object(state_gated, {"status": "open"})
    assert verdict is not None and verdict[0] is False
