"""A criterion that cannot be evaluated is not satisfied (SEC-12).

FOUND REVIEWING A NEWLY-ASSIGNED FILE, not from any audit row.

An action's declared parameter `type:` is NOT enforced anywhere.
`propose_action()` checks that REQUIRED parameters are present and
that no UNDECLARED ones were sent -- presence and names, never types.
So a parameter declared `type: number` arrives as whatever the caller
sent and reaches the comparison. Measured, on `amount less_than 1000`:

    amount = 5000     -> refused, correctly
    amount = "5000"   -> TypeError: '<' not supported between
                         instances of 'str' and 'int'
    amount = None     -> TypeError
    amount = [1, 2]   -> TypeError
    amount = True     -> PASSED

TWO FAULTS, AND THE SECOND IS THE ONE THAT MATTERS. The TypeErrors
escape as an unhandled exception from caller-supplied input -- a 500
rather than a refusal, fail-closed but a crash is not a decision.

`True < 1000` is True, because bool subclasses int. A guard reading
"amount must be under 1000" is SATISFIED by a value nobody would call
an amount, and the action proceeds. That is a criterion bypassed.

WHY THE FIX REFUSES RATHER THAN RAISING OR PASSING: a criterion that
cannot be evaluated has not been satisfied. Treating "I could not
tell" as "allowed" is the opposite of how every other gate here
resolves doubt.

WHY THE MESSAGE IS THE CRITERION'S OWN DESCRIPTION: a caller must not
be able to tell a type mismatch from a genuine violation, or the
refusal becomes a probe for how the guard is written.
"""

import pytest

from core.ontology.submission_criteria import (
    SubmissionCriteriaViolation,
    evaluate_submission_criteria,
)

UNDER_1000 = [{
    "description": "Amount must be under 1000",
    "check": "parameter", "field": "amount",
    "operator": "less_than", "value": 1000,
}]


def _evaluate(parameters, criteria=UNDER_1000):
    evaluate_submission_criteria(criteria, None, parameters, None)


class TestUncomparableValuesAreRefused:
    @pytest.mark.parametrize("value", ["5000", "50", None, [1, 2], {"a": 1}])
    def test_a_value_that_cannot_be_ordered(self, value):
        """These raised a raw TypeError out of the evaluator before."""
        with pytest.raises(SubmissionCriteriaViolation):
            _evaluate({"amount": value})

    def test_a_bool_does_not_satisfy_a_numeric_guard(self):
        """THE BYPASS. True < 1000 is True in Python, so this PASSED
        and the action proceeded with a value that is not an amount."""
        with pytest.raises(SubmissionCriteriaViolation):
            _evaluate({"amount": True})

    def test_the_refusal_is_indistinguishable_from_a_real_violation(self):
        """Otherwise the error is a probe for how the guard is written."""
        with pytest.raises(SubmissionCriteriaViolation) as mismatch:
            _evaluate({"amount": "5000"})
        with pytest.raises(SubmissionCriteriaViolation) as genuine:
            _evaluate({"amount": 5000})

        assert str(mismatch.value) == str(genuine.value)


class TestWhatMustStillWork:
    """THE OPPOSITE DIRECTION. A guard refusing every comparison would
    make every criterion unsatisfiable and block all writes."""

    def test_a_number_under_the_limit_passes(self):
        _evaluate({"amount": 500})

    def test_a_number_over_the_limit_is_refused(self):
        with pytest.raises(SubmissionCriteriaViolation):
            _evaluate({"amount": 5000})

    def test_floats_still_order(self):
        _evaluate({"amount": 999.5})

    def test_strings_still_order_against_strings(self):
        """Ordering is not numbers-only. A criterion comparing two
        strings is legitimate and must keep working."""
        criteria = [{"description": "name before m", "check": "parameter",
                     "field": "name", "operator": "less_than", "value": "m"}]
        _evaluate({"name": "alice"}, criteria)

    def test_equals_is_unguarded_and_still_type_strict(self):
        """`equals` never raised -- Python compares mismatched types as
        unequal -- so it is deliberately left alone, and a string still
        does not equal a number."""
        criteria = [{"description": "amount is 1000", "check": "parameter",
                     "field": "amount", "operator": "equals", "value": 1000}]

        with pytest.raises(SubmissionCriteriaViolation):
            _evaluate({"amount": "1000"}, criteria)
        _evaluate({"amount": 1000}, criteria)

    def test_in_is_unguarded(self):
        criteria = [{"description": "region is known", "check": "parameter",
                     "field": "region", "operator": "in",
                     "value": ["us-west", "us-east"]}]

        _evaluate({"region": "us-west"}, criteria)
        with pytest.raises(SubmissionCriteriaViolation):
            _evaluate({"region": "eu-west"}, criteria)

    def test_a_bool_against_a_bool_still_orders(self):
        """The guard rejects a MISMATCH, not bools themselves."""
        criteria = [{"description": "flag at most True", "check": "parameter",
                     "field": "flag", "operator": "less_than_or_equal", "value": True}]

        _evaluate({"flag": False}, criteria)
