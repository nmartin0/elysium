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

import dataclasses as _dataclasses
import operator as _operator
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from core.intermediate_layer.auth import UserRecord

PARAMETER_PREFIX = "parameter."
USER_PREFIX = "user."
PROPOSER_PREFIX = "proposer."

# THE VOCABULARY, AS TYPES. These two Literals are the single source of
# truth for what a criterion may say, and they are types rather than
# constants deliberately: mypy checks them, and the schema-load
# validation below gets them for free instead of restating them.
#
# This replaced a hand-rolled set of frozensets. The problem that
# produced was not the checking itself but WHERE THE VOCABULARY LIVED:
# core/ontology/action_types.py needs it too and is a SIBLING of this
# module in pyproject.toml's core.ontology layering, so it may not
# import from here. Every arrangement of shared constants ran into
# that. A type has no such problem, because nothing has to import it
# -- validate_action_type_criteria() below walks a plain dict.
CheckKind = Literal["current_state", "parameter", "user"]

# What a "user" criterion may read: the acting principal's own
# attributes, and nothing else. All three of UserRecord's fields are
# allowed, following Foundry's Current User template directly -- their
# docs describe checking "a user's ID, group memberships via group
# IDs, or any other multipass attribute available", so role (our
# nearest thing to a group) and security_value (our nearest thing to
# an Organization attribute) both belong here rather than only user_id.
#
# NOTE the deliberate overlap with RBAC that this accepts. A criterion
# on role_name says something an execute: grant can also say, and the
# two could disagree. Foundry lives with that because criteria are its
# ONLY fine-grained "who" mechanism; we have grants as well. Kept
# anyway, on precedent, because the alternative is a rule a deployment
# author has to learn from an error message rather than from Foundry's
# own documented model.
UserField = Literal["user_id", "security_value", "role_name"]
OperatorName = Literal[
    "equals", "not_equals", "greater_than", "less_than",
    "greater_than_or_equal", "less_than_or_equal", "in",
]

_OPERATORS = {
    "equals": _operator.eq,
    "not_equals": _operator.ne,
    "greater_than": _operator.gt,
    "less_than": _operator.lt,
    "greater_than_or_equal": _operator.ge,
    "less_than_or_equal": _operator.le,
    "in": lambda actual, expected: actual in expected,
}

# The one place the Literal above and the dispatch table could still
# drift: OperatorName says what a schema may DECLARE, _OPERATORS says
# what this module can EXECUTE. Adding to one and forgetting the other
# would mean either a criterion that validates at load and explodes at
# proposal time, or an operator nobody can reach.
#
# Checked at import, so it fails when the module is first loaded rather
# than when someone happens to use the mismatched operator. Raised
# rather than asserted: `python -O` strips assert statements, and this
# is a real invariant, not a debugging aid.
_USER_RECORD_FIELDS = {f.name for f in _dataclasses.fields(UserRecord)}
if not set(get_args(UserField)) <= _USER_RECORD_FIELDS:
    # The same class of drift as the operator check below: UserField
    # says what a schema may read, UserRecord says what actually
    # exists. Renaming a field on UserRecord without updating this
    # would give a criterion that validates at load and raises
    # AttributeError at proposal time.
    raise RuntimeError(
        "submission_criteria: UserField names attributes UserRecord does not have -- "
        f"{sorted(set(get_args(UserField)) - _USER_RECORD_FIELDS)}."
    )

if set(get_args(OperatorName)) != set(_OPERATORS):
    raise RuntimeError(
        "submission_criteria: OperatorName and _OPERATORS disagree -- "
        f"declared-only {sorted(set(get_args(OperatorName)) - set(_OPERATORS))}, "
        f"executable-only {sorted(set(_OPERATORS) - set(get_args(OperatorName)))}."
    )


class Criterion(BaseModel):
    """One submission criterion, as a deployment declares it.

    WHY A MODEL RATHER THAN HAND-WRITTEN CHECKS. evaluate_submission_
    criteria() below rejects an unknown check kind and an unknown
    operator -- but only when a criterion is actually REACHED, which is
    at proposal time, on a real user's write, in a running deployment.
    A deployment declaring `check: currentstate` used to start cleanly,
    pass scripts/lint_deployment.py, and fail on the first person to
    use that action.

    Every one of these constraints depends on the criterion alone, so
    all of them can be settled at load. Declaring them as a model gets
    that without a second copy of the vocabulary: `check` and
    `operator` are the same Literals the evaluator dispatches on.

    extra="forbid" is deliberate. An unrecognised key is far more
    likely a misspelling of a real one than a note the author wanted
    kept, and silently dropping it is how a criterion ends up meaning
    something other than it reads.

    `value` is Any and REQUIRED. Any because a criterion legitimately
    compares against strings, numbers, booleans and lists; required
    because an absent value is far more likely an unfinished criterion
    than a deliberate comparison against None.
    """

    model_config = ConfigDict(extra="forbid")

    description: str
    check: CheckKind
    field: str
    operator: OperatorName
    value: Any

    @model_validator(mode="after")
    def _user_field_must_be_a_real_user_attribute(self) -> "Criterion":
        # `field` cannot be one Literal for every check kind: for
        # current_state it is an object field, for parameter a
        # parameter name -- both open sets known only to a deployment.
        # For "user" it IS a closed set, so it is checked here rather
        # than left to a getattr at proposal time.
        if self.check == "user" and self.field not in get_args(UserField):
            raise ValueError(
                f"check 'user' reads {sorted(get_args(UserField))}, got {self.field!r}"
            )
        return self


def validate_action_type_criteria(action_types: dict) -> None:
    """Reject a malformed criterion at SCHEMA-LOAD time.

    Walks the action_types mapping directly rather than being called
    from core/ontology/action_types.py, which does the same traversal
    for everything else about an action type. That module is a SIBLING
    of this one in pyproject.toml's core.ontology layering and may not
    import from here -- and walking a plain dict is not importing it.

    The cost of that arrangement, stated plainly: this has to be CALLED
    by whatever loads a deployment, so it can be forgotten in a way
    action_types.py's own checks cannot. Both real callers -- core/
    deployment_loader.py and scripts/lint_deployment.py -- have a test
    that fails if the call is dropped.

    Criteria are declared PER SUB_WRITE, which is where propose_action()
    reads them from; one attached at action level is silently ignored
    rather than applied.
    """
    for action_type_name, action_def in action_types.items():
        for index, sub_write in enumerate(action_def.get("sub_writes") or []):
            criteria = sub_write.get("submission_criteria")
            if criteria is None:
                continue
            where = f"Action type {action_type_name!r}: sub_writes[{index}].submission_criteria"
            if not isinstance(criteria, list):
                raise ValueError(f"{where} must be a list, got {type(criteria).__name__}.")
            for criterion_index, criterion in enumerate(criteria):
                try:
                    Criterion.model_validate(criterion)
                except ValidationError as exc:
                    # Re-raised as ValueError, matching every other
                    # schema-load failure in this project: a deployment
                    # author sees one kind of error for one kind of
                    # mistake, and core/deployment_loader.py's callers
                    # do not have to know pydantic exists.
                    raise ValueError(f"{where}[{criterion_index}] is invalid: {exc}") from exc


class SubmissionCriteriaViolation(ValueError):
    # A ValueError subclass, deliberately -- AgentLoop can catch this
    # SPECIFICALLY (distinct from a generic invalid step -- see the
    # agentic-loop integration work on this branch), so a violated
    # criterion is tagged and recovered from differently than a
    # hallucinated field name or a plain RBAC denial, while still
    # reaching the model through the same kind of rejected-step note
    # every other boundary in this system already uses.
    pass


def _resolve_expected(value_spec, parameters: dict, user_record: UserRecord | None,
                       proposer: UserRecord | None = None):
    """Resolves a criterion's `value:` side, the same way a mutation's is.

    THREE KINDS, matching _resolve_mutation_value() exactly:
      - a LITERAL, used as-is
      - "parameter.<name>", one of the action's own declared parameters
      - "user.<attribute>", the ACTING user's own record
      - "proposer.<attribute>", the user who PROPOSED the write being
        approved -- system-supplied, never caller-supplied

    WHY BOTH SIDES NEED TO BE DYNAMIC. Four-eyes approval is the
    motivating case and cannot be written otherwise: it compares the
    APPROVING user against the write's PROPOSER, and the proposer is
    not known when the schema is authored. A literal cannot express it.

    THE SAME VOCABULARY, DELIBERATELY, rather than a new one. The
    convention already exists on the mutation side, and extending it is
    the argument that settled `check: user` -- consistency beats a
    second syntax that does the same job differently.

    STILL NOT AN EXPRESSION LANGUAGE. A small, fixed set of string
    prefixes, for the reason this module's own docstring gives about
    its operator set: a surface small enough to validate, rather than
    something needing an evaluator.

    AN UNRESOLVABLE REFERENCE RAISES rather than comparing against
    None. A criterion whose expected value silently became None would
    compare unequal to almost anything -- so a four-eyes rule reading
    "the approver must not be the proposer" would PASS for every
    approver, including the proposer. Failing loudly is the only safe
    direction when the alternative is a rule that quietly stops
    applying.
    """
    if not isinstance(value_spec, str):
        return value_spec

    if value_spec.startswith(PARAMETER_PREFIX):
        name = value_spec[len(PARAMETER_PREFIX):]
        if name not in parameters:
            raise ValueError(
                f"submission_criteria: {value_spec!r} refers to a parameter this "
                f"action did not supply -- declared parameters: {sorted(parameters)}"
            )
        return parameters[name]

    if value_spec.startswith(PROPOSER_PREFIX):
        # SYSTEM-SUPPLIED, NEVER CALLER-SUPPLIED, and that is the whole
        # reason this prefix exists rather than reusing
        # "parameter.proposed_by".
        #
        # A parameter is filled in by whoever proposes the write. A
        # four-eyes rule reading `value: parameter.proposed_by` is
        # therefore trivially defeated: the proposer passes somebody
        # else's user id and approves their own write. The rule would
        # be present, evaluated, and useless.
        #
        # Same argument as user.security_value on the mutation side:
        # the values a rule depends on for its OWN integrity cannot
        # come from the party the rule constrains.
        if proposer is None:
            raise ValueError(
                f"submission_criteria: {value_spec!r} was evaluated without a "
                f"proposer -- it is only meaningful when approving an existing "
                f"pending write"
            )
        attribute = value_spec[len(PROPOSER_PREFIX):]
        if not hasattr(proposer, attribute):
            raise ValueError(
                f"submission_criteria: {value_spec!r} names no attribute of a user record"
            )
        return getattr(proposer, attribute)

    if value_spec.startswith(USER_PREFIX):
        attribute = value_spec[len(USER_PREFIX):]
        if user_record is None:
            # Same refusal as a "user" CHECK without an acting user,
            # and for the same reason: guessing would either weaken a
            # rule or invent a violation.
            raise ValueError(
                f"submission_criteria: {value_spec!r} was evaluated without an acting user"
            )
        if not hasattr(user_record, attribute):
            raise ValueError(
                f"submission_criteria: {value_spec!r} names no attribute of a user record"
            )
        return getattr(user_record, attribute)

    return value_spec


def evaluate_submission_criteria(criteria: list[dict] | None, current_state: dict | None,
                                  parameters: dict, user_record: UserRecord | None,
                                  proposer: UserRecord | None = None) -> None:
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
        elif check_kind == "user":
            # NEVER SKIPS, unlike the two above. A "current_state"
            # criterion skips on create because no prior object exists,
            # and a "parameter" criterion skips when this call does not
            # supply that parameter -- in both cases there is genuinely
            # nothing for the rule to say. There is always an acting
            # user, so a rule about them always applies.
            #
            # security_value and role_name are Optional on UserRecord.
            # A user with neither compares as None and fails the
            # criterion, which denies -- the fail-safe direction, and
            # the reason this reads the attribute rather than skipping
            # when it is unset.
            if user_record is None:
                # Callers that cannot know the acting user must filter
                # "user" criteria out BEFORE calling -- core/llm/
                # agent_step_prompt.py does. Reaching here means one
                # slipped through, and guessing (skip? deny?) would
                # either weaken a rule or invent a violation, so
                # neither: refuse to produce a verdict at all.
                raise ValueError(
                    "submission_criteria: a 'user' criterion was evaluated without an acting user"
                )
            actual_value = getattr(user_record, field_name)
        elif check_kind == "parameter":
            if field_name not in parameters:
                # This call doesn't supply the parameter this rule is
                # about -- nothing for the rule to say here.
                continue
            actual_value = parameters[field_name]
        else:
            raise ValueError(f"Unknown submission_criteria check kind: {check_kind!r}")

        expected_value = _resolve_expected(expected_value, parameters, user_record, proposer)

        operator_fn = _OPERATORS.get(operator_name)
        if operator_fn is None:
            raise ValueError(f"Unknown submission_criteria operator: {operator_name!r}")

        if not operator_fn(actual_value, expected_value):
            raise SubmissionCriteriaViolation(criterion["description"])
