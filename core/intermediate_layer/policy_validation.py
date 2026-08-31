"""
policy_validation.py  (schema-load-time validation for policy.yaml's
role grants)

Every grant string in every role's own allowed_actions is checked
against what it ACTUALLY references -- an object type, a field, an
action type, a tool -- being real, not just well-formed. See
core/intermediate_layer/auth.py's authorize() for the runtime
counterpart this validates against: authorize() does a bare, EXACT
string match (action_id in role["allowed_actions"]), with no parsing
or existence-checking of its own at all -- a typo'd grant
("excute:TransferFunds" instead of "execute:TransferFunds", or
"read:Custmer" instead of "read:Customer") doesn't fail loudly
anywhere; it just silently never matches anything, forever, and the
role that has it is quietly missing an intended permission with no
error, no warning, nothing -- exactly the "silently wrong" failure
mode this project has consistently refused to allow anywhere else
(core/ontology/action_types.py's own module docstring names the
identical class of gap for action_type mutations, the direct
precedent this module follows).

WHY schema-load time, not authorize() time: authorize() runs on
every single access check in the system -- adding real-reference
validation there would mean paying this cost on every read, every
write, every tool call, forever, for a condition that can only ever
be true or false once, at load time, and never changes for the
lifetime of a running deployment. Checking here, once, at startup, is
strictly better: catches the exact same bug, for free at runtime,
before the deployment ever serves a single real request.

THE SIX REAL GRANT PATTERNS -- found by grepping every real call site
that constructs an action_id string to pass to authorize(), not
assumed or invented:
  - "manage:users" -- an exact, fixed literal (core/user_directory.py,
    api/routes.py). No object/field/action to reference at all.
  - "execute:<ActionName>" -- ActionName must be a real, declared
    action_type (core/ontology/write_mediator.py).
  - "tool:<ToolName>" -- ToolName must be in this deployment's own
    enabled_tools (core/agent/agentic_loop.py).
  - "write:<Type>.<field>" -- Type must be a real object_type, field
    must be one of its real, declared fields (or its own id_field --
    see this module's own _valid_field_names() for why that's
    separately valid). Only ever constructed for the cross-type RBAC
    check (Option B) once a sub_writes action spans more than one
    object type (core/ontology/write_mediator.py).
  - "read:<Type>.<field>" -- same shape as write:, TYPE-level read
    counterpart (core/ontology/mediator.py, core/memory/guard.py).
  - "read:<Type>" (no dot) -- Type must be real; the TYPE-level read
    grant gating schema visibility itself (core/ontology/mediator.py).

Anything that doesn't match ANY of these six patterns is rejected
outright, not silently accepted -- almost certainly a typo of one of
the six above (e.g. a stray colon, a misspelled prefix), and letting
it through unchecked would just be a DIFFERENT, undetectable version
of the same silent-typo problem this module exists to catch.

Deliberately does NOT check whether a real, valid grant is actually
USED by anything (e.g. a write:Order.total grant nobody's action
mutations ever require) -- that's a genuinely different kind of
question (an unused-permission lint, closer to opinion than
correctness) from "does this grant reference something that exists,"
which is the only thing checked here.
"""

VALID_PREFIXES = ("manage:", "execute:", "tool:", "write:", "read:")


def validate_roles(roles: dict, object_types: dict, action_types: dict, enabled_tools: list[str]) -> None:
    for role_name, role_def in roles.items():
        for grant in role_def.get("allowed_actions", []):
            _validate_one_grant(role_name, grant, object_types, action_types, enabled_tools)


def _validate_one_grant(role_name: str, grant: str, object_types: dict, action_types: dict,
                         enabled_tools: list[str]) -> None:
    if grant == "manage:users":
        return

    if grant.startswith("execute:"):
        action_name = grant.removeprefix("execute:")
        if action_name not in action_types:
            raise ValueError(
                f"Role {role_name!r}: grant {grant!r} references unknown action "
                f"type {action_name!r} -- not declared anywhere in this "
                f"deployment's own ontology_schema.yaml."
            )
        return

    if grant.startswith("tool:"):
        tool_name = grant.removeprefix("tool:")
        if tool_name not in enabled_tools:
            raise ValueError(
                f"Role {role_name!r}: grant {grant!r} references tool "
                f"{tool_name!r}, which isn't in this deployment's own "
                f"config.yaml tools.enabled list."
            )
        return

    if grant.startswith("write:") or grant.startswith("read:"):
        _validate_type_or_field_grant(role_name, grant, object_types)
        return

    raise ValueError(
        f"Role {role_name!r}: grant {grant!r} doesn't match any recognized "
        f"pattern ({', '.join(VALID_PREFIXES)}, or the literal 'manage:users') "
        f"-- almost certainly a typo of one of these; see this module's own "
        f"docstring for the full, real set."
    )


def _validate_type_or_field_grant(role_name: str, grant: str, object_types: dict) -> None:
    prefix, _, rest = grant.partition(":")
    prefix += ":"
    # rest is EITHER "<Type>" (read: only -- the type-level grant) or
    # "<Type>.<field>" -- split on the FIRST "." specifically, since a
    # field name itself is never expected to contain one.
    object_type, sep, field_name = rest.partition(".")

    if object_type not in object_types:
        raise ValueError(
            f"Role {role_name!r}: grant {grant!r} references unknown object "
            f"type {object_type!r} -- not declared anywhere in this "
            f"deployment's own ontology_schema.yaml."
        )

    if not sep:
        # "read:<Type>" with no field -- fine, the type-level grant.
        # "write:<Type>" with no field would be meaningless (write: is
        # only ever constructed as write:<Type>.<field>) -- reject it
        # explicitly rather than silently accepting a grant that could
        # never match anything real.
        if prefix == "write:":
            raise ValueError(
                f"Role {role_name!r}: grant {grant!r} is a type-level write: "
                f"grant, which is never constructed anywhere -- write: is "
                f"always write:<Type>.<field>; this can never match a real "
                f"authorize() call."
            )
        return

    valid_field_names = _valid_field_names(object_types[object_type])
    if field_name not in valid_field_names:
        raise ValueError(
            f"Role {role_name!r}: grant {grant!r} references unknown field "
            f"{field_name!r} on {object_type!r} -- not declared anywhere in "
            f"this deployment's own ontology_schema.yaml."
        )


def _valid_field_names(type_schema: dict) -> set[str]:
    # id_field is a real, addressable field (read:<Type>.<id_field> is
    # a completely ordinary, common grant throughout this project's
    # own real deployments) even though it isn't listed under the
    # type's own "fields" -- see core/deployment_loader.py's own
    # schema handling for why. Matches core/ontology/action_types.py's
    # own, identical reasoning for mutation property names.
    return set(type_schema["fields"]) | {type_schema["id_field"]}


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# CONTEXT: this module's own existence closes an item from a tracked,
# ordered list of deferred work built up over a long prior session --
# "load-time role-vs-real-action-name checking," done at the same time
# as core/ontology/action_types.py's own sibling addition (mutation-
# property-name checking) and the "missing sub_writes" fix (see that
# module's own AI-notes for the full history of that specific gap).
# Both were explicitly sequenced BEFORE the next items on that same
# list (a standalone schema-linter CLI, then a real, deliberately-
# authored multi-object action_type) specifically so those later
# items would build on genuinely hardened validation, not something
# still catching up.
#
# DEFERRED (known, intentional, not yet built):
# - VALID_PREFIXES is declared but only used inside the final
#   unrecognized-grant error message -- if a SEVENTH real grant
#   pattern is ever added anywhere in the codebase (a new authorize()
#   call site constructing some new prefix), this module needs a
#   matching new branch in _validate_one_grant() AND an update to
#   VALID_PREFIXES, or that new pattern would be silently rejected as
#   "unrecognized" by THIS validator even though it's real and
#   correct. There's no structural guarantee these two things
#   (authorize()'s real call sites, and this module's own recognized-
#   pattern list) stay in sync automatically -- worth re-grepping
#   every real f"...:{...}" construction site (the same search this
#   module's own docstring describes doing to find the current six)
#   if this module's own tests ever start failing against a real
#   policy.yaml for no apparent reason.
# - Does NOT check whether a role's OWN combination of grants is
#   coherent in any deeper sense (e.g. execute:TransferFunds without
#   the corresponding write:Account.balance grant a cross-type action
#   might need) -- each grant is validated purely independently,
#   against the schema, never against what OTHER grants the same role
#   also holds. That would be a different, more invasive kind of
#   check (closer to "does this role actually work end to end for its
#   own intended actions" than "does this grant reference something
#   real"), not attempted here.
