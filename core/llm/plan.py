"""
plan.py  (a plan's handles: validating them, and resolving them)

AL-4, first commit. The planner names a result it cannot read --
`$a` -- and the executor substitutes the value. That is the whole
security property: a planted instruction in a field value cannot
change WHICH steps run, because the steps were fixed before any value
was read.

001AGENTLOOP specifies the shape: "the planner sees HANDLES, not
values". It is CaMeL's rule word for word -- untrusted results are
held in memory the privileged model "can manipulate by reference
only".

IT LIVES IN core/llm/ BECAUSE THE CONTRACT SAID SO, and the story is
the same one core/filters.py tells about itself. It was written in
core/agent/, where the executor lives -- and the moment the PLANNER
needed it too, import-linter refused: core.agent sits ABOVE core.llm,
so the prompt module cannot reach up into the loop.

A plan is a message format BETWEEN the two. The planner writes it, the
executor runs it, and a vocabulary the lower layer cannot reach is in
the wrong place. filters.py moved down for exactly this reason; so
does this.

NO MODEL IS INVOLVED IN THIS FILE, deliberately, and it is the first
commit for that reason. Handle resolution is pure: a plan in, a
resolved step out. Getting `$a` wrong SILENTLY is how a plan reads the
wrong object, and silence is exactly what a test can catch when there
is no model in the way.

== WHAT COUNTS AS A HANDLE, AND WHY THE RULE IS NARROW ==

A value is a handle ONLY when the entire string is `$` followed by an
identifier-shaped name. Not a prefix, not a substring, not
interpolation.

`$100` IS NOT A HANDLE. It is a price, and a customer really can be
called "$100 Store". Identifiers must start with a letter, so a
leading digit settles it without anyone having to escape anything.

AN UNKNOWN HANDLE IS AN ERROR, NOT A LITERAL. `$custmer` -- a typo --
could be treated as the string "$custmer" and used as a filter value.
It would match nothing, the step would return empty, and the plan
would carry on producing a confident answer about no data. Refusing is
the only option that cannot be mistaken for a result.

ONLY VALUES, NEVER KEYS. A dict's keys here are field names, not data,
and resolving them would let a plan choose which FIELD to read from
something it read earlier -- turning a data value back into control
flow, which is the one thing this design exists to prevent.

REFERENCES POINT BACKWARDS ONLY. A plan is a list, and a step may name
any step before it. Forward and self references are refused, which
makes cycles impossible without a cycle check.
"""

from __future__ import annotations

import re
from typing import Any

# `$` then an identifier: a letter or underscore, then letters, digits
# or underscores. Anchored at both ends, so this matches the WHOLE
# value or nothing.
_HANDLE = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*)$")

# A step's own id, same shape as what a handle may name.
_STEP_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PlanError(ValueError):
    """A plan that cannot be executed as written.

    A ValueError SUBCLASS deliberately: the agent loop catches
    (ValueError, TypeError, PermissionError) and turns them into a
    recoverable mistake the model can be told about. A new exception
    type would sail past that handler and out of the loop, which is
    AL-1's shape -- a model-written value crashing /query outside the
    error handling.
    """


def validate_plan(plan: Any) -> list[dict]:
    """Every id declared once, every handle pointing backwards.

    TAKES `Any` AND RETURNS THE PLAN. It validates the type itself --
    a caller passing `parsed.get("plan")` has no idea what it holds,
    which is the whole reason to call this -- and returning the
    validated list lets the caller use it without a second cast or a
    separate narrowing step that could drift from the check.

    CHECKED BEFORE ANYTHING RUNS. A plan whose third step names a
    handle that does not exist is broken whether or not the first two
    would have succeeded, and finding that out after two real reads
    means two audit entries for a query that was never going to work.
    """
    if not isinstance(plan, list):
        raise PlanError(f"A plan must be a list of steps, not {type(plan).__name__}")
    if not plan:
        raise PlanError("A plan must have at least one step")

    seen: set[str] = set()
    for position, step in enumerate(plan):
        if not isinstance(step, dict):
            raise PlanError(f"Step {position} is not an object")
        step_id = step.get("id")
        if not isinstance(step_id, str) or not _STEP_ID.match(step_id):
            raise PlanError(
                f"Step {position} needs an 'id' that starts with a letter and "
                f"holds only letters, digits and underscores; got {step_id!r}"
            )
        if step_id in seen:
            # TWO STEPS WITH ONE NAME means a handle to it is
            # ambiguous, and the ambiguity would be resolved silently
            # by whichever won.
            raise PlanError(f"Step id {step_id!r} is used more than once")

        for handle in _handles_in(step):
            if handle == step_id:
                raise PlanError(f"Step {step_id!r} refers to its own result")
            if handle not in seen:
                # Covers both a forward reference and a typo, and the
                # message cannot tell them apart because neither can
                # the plan.
                raise PlanError(
                    f"Step {step_id!r} uses ${handle}, which is not the id of "
                    f"any earlier step. Steps may only use results from steps "
                    f"before them."
                )
        seen.add(step_id)
    return plan


def _handles_in(value: Any) -> list[str]:
    """Every handle inside a value, at any depth.

    VALUES ONLY. Dict keys are skipped -- see the module docstring for
    why resolving them would turn data back into control flow.
    """
    if isinstance(value, str):
        match = _HANDLE.match(value)
        return [match.group(1)] if match else []
    if isinstance(value, dict):
        return [h for v in value.values() for h in _handles_in(v)]
    if isinstance(value, (list, tuple)):
        return [h for v in value for h in _handles_in(v)]
    return []


def resolve_handles(value: Any, results: dict[str, Any]) -> Any:
    """`value` with every handle replaced by what that step returned.

    SUBSTITUTES THE VALUE ITSELF, not a string of it. `$a` resolving
    to `["1", "2"]` becomes the list, not `'["1", "2"]'` -- the
    executor needs the ids, and a step that received the string form
    would search for an object whose id is literally a JSON array.

    RAISES ON AN UNKNOWN HANDLE even though validate_plan() checks the
    same thing. The two guard different moments: validation runs once
    before the plan starts, this runs per step, and a step reached
    through some path validation did not anticipate must not quietly
    substitute nothing.
    """
    if isinstance(value, str):
        match = _HANDLE.match(value)
        if match is None:
            return value
        name = match.group(1)
        if name not in results:
            raise PlanError(f"${name} has no result -- it was never executed")
        return results[name]
    if isinstance(value, dict):
        # KEYS PASS THROUGH UNTOUCHED. Only the values are resolved.
        return {key: resolve_handles(item, results) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_handles(item, results) for item in value]
    return value


def resolve_step(step: dict, results: dict[str, Any]) -> dict:
    """One planned step, ready to execute.

    `id` IS DROPPED. It names the step for other steps to refer to and
    means nothing to a handler -- and leaving it in would put an extra
    key into every gathered entry, which is prompt tokens on every
    later hop for a value the model chose itself.
    """
    return {
        key: resolve_handles(item, results)
        for key, item in step.items()
        if key != "id"
    }
