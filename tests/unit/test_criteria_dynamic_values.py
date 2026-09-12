"""
A criterion's `value:` side can name a parameter or the acting user.

WHY BOTH SIDES MUST BE DYNAMIC. Four-eyes approval is the motivating
case and cannot be written otherwise: it compares the APPROVING user
against the write's PROPOSER, and the proposer is not known when the
schema is authored. A literal cannot express it.

THE SAME VOCABULARY AS A MUTATION'S VALUE, deliberately --
"parameter.<name>" and "user.<attribute>" already resolve on that side,
and extending the convention is the argument that settled `check:
user`. Consistency beats a second syntax doing the same job
differently.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.submission_criteria import (
    SubmissionCriteriaViolation,
    evaluate_submission_criteria,
)

ALICE = UserRecord("alice", "us-west", "analyst")


def _four_eyes():
    """"The approving user must not be the one who proposed it."

    USES proposer.user_id, NOT parameter.proposed_by, and the
    difference is the entire security of the rule. A parameter is
    filled in by whoever proposes the write, so a four-eyes rule
    reading `parameter.proposed_by` is trivially defeated: the proposer
    passes somebody else's id and approves their own write. The rule
    would be present, evaluated, and useless.

    Same argument as user.security_value on the mutation side -- the
    values a rule depends on for its OWN integrity cannot come from the
    party the rule constrains.
    """
    return [{
        "check": "user",
        "field": "user_id",
        "operator": "not_equals",
        "value": "proposer.user_id",
        "description": "A write must be approved by someone other than its proposer.",
    }]


class TestFourEyes:
    def test_a_different_user_may_approve(self):
        proposer = UserRecord("bob", "us-west", "analyst")

        evaluate_submission_criteria(_four_eyes(), None, {}, ALICE, proposer=proposer)

    def test_the_proposer_may_not_approve_their_own_write(self):
        # THE WHOLE POINT. Before dynamic values this rule could not be
        # written at all: the proposer is not known when the schema is.
        with pytest.raises(SubmissionCriteriaViolation, match="other than its proposer"):
            evaluate_submission_criteria(_four_eyes(), None, {}, ALICE, proposer=ALICE)


class TestUserReferences:
    def test_a_user_attribute_resolves_on_the_value_side(self):
        # Same tenant: allowed. The MAC value is compared against the
        # acting user's own rather than a hardcoded one.
        criteria = [{
            "check": "parameter", "field": "target_region", "operator": "equals",
            "value": "user.security_value",
            "description": "You may only act within your own region.",
        }]

        evaluate_submission_criteria(criteria, None, {"target_region": "us-west"}, ALICE)

    def test_a_different_tenant_is_refused(self):
        criteria = [{
            "check": "parameter", "field": "target_region", "operator": "equals",
            "value": "user.security_value",
            "description": "You may only act within your own region.",
        }]

        eu_user = UserRecord("carol", "eu-west", "analyst")

        with pytest.raises(SubmissionCriteriaViolation, match="your own region"):
            evaluate_submission_criteria(criteria, None, {"target_region": "us-east"}, eu_user)


class TestLiteralsAreUnchanged:
    def test_a_literal_value_still_compares_as_itself(self):
        # THE CONTROL, and the overwhelmingly common case: every
        # criterion written today holds a literal, and a resolver that
        # mangled them would break every existing deployment.
        criteria = [{
            "check": "user", "field": "role_name", "operator": "equals", "value": "analyst",
            "description": "Only analysts.",
        }]

        evaluate_submission_criteria(criteria, None, {}, ALICE)

    def test_a_non_string_literal_passes_through(self):
        # Numbers and booleans are not references and must not be
        # inspected for prefixes.
        criteria = [{
            "check": "parameter", "field": "amount", "operator": "less_than", "value": 100,
            "description": "Under a hundred.",
        }]

        evaluate_submission_criteria(criteria, None, {"amount": 50}, ALICE)


class TestUnresolvableReferences:
    def test_a_missing_parameter_raises_rather_than_comparing_to_none(self):
        """THE FAIL-SAFE DIRECTION, and the reason this is not lenient.

        A criterion whose expected value silently became None would
        compare unequal to almost anything -- so a four-eyes rule
        reading "the approver must not be the proposer" would PASS for
        every approver, INCLUDING the proposer. The rule would look
        present and enforce nothing.
        """
        missing_param = [{
            "check": "user", "field": "user_id", "operator": "not_equals",
            "value": "parameter.nobody_supplied_this", "description": "Never passes.",
        }]

        with pytest.raises(ValueError, match="did not supply"):
            evaluate_submission_criteria(missing_param, None, {}, ALICE)

    def test_a_user_reference_without_an_acting_user_raises(self):
        criteria = [{
            "check": "parameter", "field": "region", "operator": "equals",
            "value": "user.security_value", "description": "Own region only.",
        }]

        with pytest.raises(ValueError, match="without an acting user"):
            evaluate_submission_criteria(criteria, None, {"region": "us-west"}, None)

    def test_a_user_reference_to_no_such_attribute_raises(self):
        criteria = [{
            "check": "parameter", "field": "region", "operator": "equals",
            "value": "user.favourite_colour", "description": "Nonsense.",
        }]

        with pytest.raises(ValueError, match="no attribute"):
            evaluate_submission_criteria(criteria, None, {"region": "us-west"}, ALICE)


class TestTheProposerReference:
    def test_a_proposer_reference_without_a_proposer_raises(self):
        # Only meaningful when approving an EXISTING pending write.
        # Evaluated at propose time there is no proposer yet, and
        # resolving to None would make the rule pass for everyone.
        with pytest.raises(ValueError, match="without a proposer"):
            evaluate_submission_criteria(_four_eyes(), None, {}, ALICE)

    def test_a_proposer_reference_to_no_such_attribute_raises(self):
        criteria = [{
            "check": "user", "field": "user_id", "operator": "not_equals",
            "value": "proposer.favourite_colour", "description": "Nonsense.",
        }]

        with pytest.raises(ValueError, match="no attribute"):
            evaluate_submission_criteria(criteria, None, {}, ALICE, proposer=ALICE)

    def test_a_parameter_cannot_stand_in_for_the_proposer(self):
        """THE ATTACK THIS PREVENTS, written out so it is not re-invented.

        With `value: parameter.proposed_by`, alice proposes a write,
        passes "bob" as proposed_by, and then approves it herself --
        because the rule compares her against the string she chose.

        The rule below uses the same shape with a parameter, and this
        test asserts it is defeated. It exists to make the difference
        between the two prefixes concrete rather than theoretical.
        """
        defeatable = [{
            "check": "user", "field": "user_id", "operator": "not_equals",
            "value": "parameter.proposed_by",
            "description": "A write must be approved by someone else.",
        }]

        # alice proposed it, and says bob did.
        evaluate_submission_criteria(defeatable, None, {"proposed_by": "bob"}, ALICE)

        # The same rule via proposer. cannot be lied to.
        with pytest.raises(SubmissionCriteriaViolation):
            evaluate_submission_criteria(
                _four_eyes(), None, {"proposed_by": "bob"}, ALICE, proposer=ALICE,
            )
