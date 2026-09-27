"""A criterion may name a DECLARED field of a user record, nothing
else (SEC-26).

`_resolve_expected` gated `user.<attribute>` and `proposer.<attribute>`
with `hasattr`, which is true of every method and every dunder as well
as the three real fields. Measured before the fix:

    user.user_id        -> 'alice'
    user.security_value -> 'us-west'
    user.role_name      -> 'agent'
    user.role           -> refused        (a plausible typo, correctly)
    user.__class__      -> <class ...>
    user.__eq__         -> <bound method ...>
    user.__doc__        -> 'UserRecord(...)'

WHY IT MATTERS DESPITE BEING UNLIKELY TO BE TYPED. A criterion whose
expected value resolves to a bound method compares unequal to
everything, so the rule is present, evaluated, and useless -- the same
shape as F-08, where a rule that looked enforced was silently skipped.
A four-eyes rule that never matches is worse than one that refuses to
load, because nothing tells you.

AND THE CONSTANT ALREADY EXISTED. `_USER_RECORD_FIELDS` sits one
screen above, used only for an import-time self-check. A constant
whose name says it constrains something, beside code that does not use
it, is the kind of claim this branch has spent its time finding wrong
in other people's files.

THE CHECK NARROWS, which is why it was safe to take while closing a
branch: everything that was accepted AND was genuinely a field is
still accepted. Nothing stops working unless it was already
meaningless.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.submission_criteria import (
    _USER_RECORD_FIELDS,
    SubmissionCriteriaViolation,
    _resolve_expected,
    evaluate_submission_criteria,
)


@pytest.fixture
def user() -> UserRecord:
    return UserRecord("alice", "us-west", "agent")


class TestOnlyDeclaredFieldsResolve:
    @pytest.mark.parametrize("attribute", ["__class__", "__eq__", "__doc__", "__dict__"])
    def test_a_dunder_is_refused(self, user, attribute):
        with pytest.raises(ValueError, match="no declared field"):
            _resolve_expected(f"user.{attribute}", {}, user)

    def test_a_proposer_dunder_is_refused_too(self, user):
        """The same gate, on the side that four-eyes actually uses."""
        with pytest.raises(ValueError, match="no declared field"):
            _resolve_expected("proposer.__class__", {}, user, proposer=user)

    def test_the_refusal_lists_what_is_available(self, user):
        """A deployment author fixing a typo should not have to read
        the source to find the field names."""
        with pytest.raises(ValueError) as raised:
            _resolve_expected("user.role", {}, user)

        message = str(raised.value)
        for field in _USER_RECORD_FIELDS:
            assert field in message


class TestWhatMustStillResolve:
    """THE OPPOSITE DIRECTION. A gate that refused everything would
    break four-eyes approval entirely, which is the feature this
    resolver exists for."""

    @pytest.mark.parametrize("attribute", ["user_id", "security_value", "role_name"])
    def test_every_declared_field(self, user, attribute):
        assert _resolve_expected(f"user.{attribute}", {}, user) == getattr(user, attribute)

    def test_the_proposer_side_too(self, user):
        proposer = UserRecord("bob", "us-east", "reviewer")

        assert _resolve_expected("proposer.user_id", {}, user, proposer=proposer) == "bob"

    def test_a_literal_is_untouched(self, user):
        assert _resolve_expected("just a string", {}, user) == "just a string"
        assert _resolve_expected(1000, {}, user) == 1000

    def test_a_parameter_reference_still_works(self, user):
        assert _resolve_expected("parameter.amount", {"amount": 50}, user) == 50


class TestFourEyesStillBehaves:
    """The motivating case, end to end: an approver must not be the
    proposer. This is the rule a bound-method comparison would have
    silently disabled."""

    CRITERION = [{
        "description": "The approver must not be the proposer",
        "check": "user", "field": "user_id",
        "operator": "not_equals", "value": "proposer.user_id",
    }]

    def test_a_different_approver_passes(self):
        approver = UserRecord("bob", "us-west", "reviewer")
        proposer = UserRecord("alice", "us-west", "agent")

        evaluate_submission_criteria(self.CRITERION, None, {}, approver, proposer=proposer)

    def test_the_proposer_approving_their_own_write_is_refused(self):
        alice = UserRecord("alice", "us-west", "agent")

        with pytest.raises(SubmissionCriteriaViolation):
            evaluate_submission_criteria(self.CRITERION, None, {}, alice, proposer=alice)
