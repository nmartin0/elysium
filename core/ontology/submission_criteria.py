"""
submission_criteria.py  (business-state validation on named actions --
generic, org-agnostic)

Matches Palantir Foundry's own concept and name (their own docs:
"submission criteria... support encoding business logic into data
editing permissions"), verified directly against their documentation
before this was built, not assumed. Closes a real gap this project's
write path had: authorization (RBAC/MAC) alone never asked "given this
object's CURRENT state, does this specific change even make sense." A
fully authorized user, right role, right region, could still propose a
completely nonsensical state transition (e.g. reopening an already-
closed ticket) and nothing mechanically stopped it. This is that
mechanical check.

Structurally a property of a named ACTION TYPE, not a generic
validation bolted onto whatever "update" happens to mean for an object
type -- confirmed directly against Palantir's own docs, which attach
submission criteria to actions specifically, not objects. See
core/ontology/write_mediator.py's propose_action() for the only real
caller.

DELIBERATELY structured conditions, not a string-expression language --
unsafely evaluating arbitrary expressions is a well-understood risk
class, and Palantir's own UI is condition-template-based for the same
reason, not raw-expression-based. A fixed, small operator set instead:
equals, not_equals, greater_than, less_than, greater_than_or_equal,
less_than_or_equal, in. Covers the large majority of real business
rules (state locks, range checks, enum checks) without a general
expression evaluator.

ALLOW-framed, matching Palantir's own naming ("submission CRITERIA" --
conditions required to submit, not conditions that block): every
criterion in an action's submission_criteria list must evaluate TRUE
for the action to proceed. The FIRST one that evaluates False raises,
with its own "description" as the failure reason -- the model sees a
real, specific message through AgentLoop's rejected-step recovery path
(see SubmissionCriteriaViolation's own docstring), the same way it
already learns every other boundary in this system.

TWO check kinds, because they read from genuinely different places:
  - "current_state": the object's EXISTING value for `field`, read
    fresh from the database (see propose_action() for where this
    actually gets fetched). Answers "is this action even valid given
    how the object stands right now."
  - "parameter": the VALUE SUPPLIED for one of the action's own
    DECLARED parameters -- a genuinely different namespace than an
    object's raw field names; a parameter may have no corresponding
    object field at all. Answers "is this specific input valid,"
    independent of anything already stored.

A "parameter" criterion is silently SKIPPED if its own field isn't
supplied in this specific call's `parameters` at all -- a rule about
`amount`'s value has nothing to say about an action that was never
given an `amount`. A "current_state" criterion is skipped ONLY when
current_state is explicitly None, meaning the action's operation is
"create" -- there is no prior object to check state on at all;
evaluating one against a fabricated empty/missing value would produce
false failures (e.g. a "status must equal open" rule blocking every
single create, since a brand-new object has no status yet).
"current_state" criteria DO apply to every "update" action, regardless
of which parameters that specific call supplies -- a business-state
lock like "ticket must not be closed" should hold no matter what's
being changed about it.

Used by: core/ontology/write_mediator.py's propose_action()
"""

import operator as _operator

_OPERATORS = {
    "equals": _operator.eq,
    "not_equals": _operator.ne,
    "greater_than": _operator.gt,
    "less_than": _operator.lt,
    "greater_than_or_equal": _operator.ge,
    "less_than_or_equal": _operator.le,
    "in": lambda actual, expected: actual in expected,
}


class SubmissionCriteriaViolation(ValueError):
    # A ValueError subclass, deliberately -- AgentLoop can catch this
    # SPECIFICALLY (distinct from a generic invalid step -- see the
    # agentic-loop integration work on this branch), so a violated
    # criterion is tagged and recovered from differently than a
    # hallucinated field name or a plain RBAC denial, while still
    # reaching the model through the same kind of rejected-step note
    # every other boundary in this system already uses.
    pass


def evaluate_submission_criteria(criteria: list[dict] | None, current_state: dict | None,
                                  parameters: dict) -> None:
    # Raises SubmissionCriteriaViolation, with the FIRST failing
    # criterion's own "description," the moment one is found -- not a
    # combined report of every violation. Returns None (does nothing)
    # if every criterion passes, or if criteria is empty/None (an
    # action type with no declared rules at all).
    for criterion in criteria or []:
        check_kind = criterion["check"]
        field_name = criterion["field"]
        operator_name = criterion["operator"]
        expected_value = criterion["value"]

        if check_kind == "current_state":
            if current_state is None:
                # A "create" -- no prior object exists to check state
                # on. See module docstring for why this is a SKIP, not
                # an evaluation against a fabricated empty state.
                continue
            actual_value = current_state.get(field_name)
        elif check_kind == "parameter":
            if field_name not in parameters:
                # This call doesn't supply the parameter this rule is
                # about -- nothing for the rule to say here.
                continue
            actual_value = parameters[field_name]
        else:
            raise ValueError(f"Unknown submission_criteria check kind: {check_kind!r}")

        operator_fn = _OPERATORS.get(operator_name)
        if operator_fn is None:
            raise ValueError(f"Unknown submission_criteria operator: {operator_name!r}")

        if not operator_fn(actual_value, expected_value):
            raise SubmissionCriteriaViolation(criterion["description"])
