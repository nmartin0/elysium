"""
A parameter used only by a submission criterion is still USED.

THE LANDMINE THIS DEFUSES, recorded in ROADMAP.md and IDEAS.md before
it was fixed, and worth stating because the failure is the bad kind.

_collect_parameter_references() feeds the validator that rejects a
declared-but-unused parameter. It read criteria off `action_def`, one
level above where WriteMediator actually reads them
(sw_def["submission_criteria"]), so it found none.

Harmless while every criterion value is a LITERAL, which is all any
deployment writes today. Silently wrong the moment one is not -- and
four-eyes approval, the next product step, is exactly what makes a
criterion value dynamic: the approving user compared against the
write's proposer.

The damage would have been: a parameter used ONLY by a criterion gets
reported as declared-but-unused, the author deletes the declaration on
the validator's advice, and the criterion breaks. A validator that
tells you to remove something load-bearing is worse than one that says
nothing.
"""

from core.ontology.action_types import _collect_parameter_references

PARAMETERS = {"ticket_id": {"type": "string"}, "approver": {"type": "string"}}


def _action(criteria_on_sub_write=None, criteria_on_action=None):
    sub_write = {
        "object_type": "Ticket",
        "object_id": "parameter.ticket_id",
        "operation": "update",
        "mutations": [{"set": {"property": "state", "value": "closed"}}],
    }
    if criteria_on_sub_write is not None:
        sub_write["submission_criteria"] = criteria_on_sub_write
    action = {"parameters": PARAMETERS, "sub_writes": [sub_write]}
    if criteria_on_action is not None:
        action["submission_criteria"] = criteria_on_action
    return action


FOUR_EYES = [{"check": "user", "operator": "not_equals", "value": "parameter.approver"}]


def test_finds_a_parameter_used_only_by_a_criterion_on_the_sub_write():
    # THE REAL SHAPE. This is where WriteMediator reads criteria from,
    # and where every deployment writes them.
    assert "approver" in _collect_parameter_references(_action(criteria_on_sub_write=FOUR_EYES))


def test_still_finds_one_at_the_action_level():
    # Nothing forbids a deployment putting criteria there, and a
    # validator that quietly ignored half the file would be its own
    # version of this bug.
    assert "approver" in _collect_parameter_references(_action(criteria_on_action=FOUR_EYES))


def test_a_literal_criterion_contributes_no_reference():
    # THE CONTROL. Every criterion written today holds a literal, so a
    # collector that returned everything it saw would pass the tests
    # above while reporting nonsense -- "closed" is not a parameter.
    literal = [{"check": "user", "operator": "not_equals", "value": "alice"}]

    assert _collect_parameter_references(_action(criteria_on_sub_write=literal)) == {"ticket_id"}


def test_an_action_with_no_criteria_is_unchanged():
    # The overwhelmingly common case, and the one a fix like this most
    # easily breaks.
    assert _collect_parameter_references(_action()) == {"ticket_id"}


def test_the_validator_no_longer_calls_a_criterion_parameter_unused():
    # THE ACTUAL DAMAGE, end to end: the validator told an author to
    # delete a declaration the criterion depends on.
    from core.ontology.action_types import validate_action_types

    schema = {"Ticket": {"id_field": "ticket_id", "fields": {"state": {"data_type": "string"}}}}
    actions = {
        "CloseTicket": {
            "affected_object_types": ["Ticket"],
            "parameters": {
                "ticket_id": {"type": "object_reference", "object_type": "Ticket",
                              "required": True},
                "approver": {"type": "string", "required": True},
            },
            "sub_writes": [{
                "object_type": "Ticket",
                "object_id": "parameter.ticket_id",
                "operation": "update",
                "mutations": [{"set": {"property": "state", "value": "closed"}}],
                "submission_criteria": FOUR_EYES,
            }],
        }
    }

    validate_action_types(actions, schema)  # must not raise
