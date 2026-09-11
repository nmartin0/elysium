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

THE SEVEN REAL GRANT PATTERNS -- found by grepping every real call site
that constructs an action_id string to pass to authorize(), not
assumed or invented:
  - "manage:users" -- an exact, fixed literal (core/user_directory.py,
    api/routes.py). No object/field/action to reference at all.
  - "discover:action_types" -- an exact, fixed literal (core/ontology/
    write_mediator.py's own visible_action_types()), same shape as
    manage:users above -- a single, blanket grant, not per-action-
    type, so nothing further to validate against once the literal
    string itself matches.
  - "execute:<ActionName>" -- ActionName must be a real, declared
    action_type (core/ontology/write_mediator.py).
  - "tool:<ToolName>" -- ToolName must be in this deployment's own
    enabled_tools (core/agent/agentic_loop.py).
  - "read:<Type>.<field>" -- Type must be a real object_type, field
    must be one of its real, declared fields (or its own id_field --
    see this module's own _valid_field_names() for why that's
    separately valid). "read:<Type>" with no field is the type-level
    grant (core/ontology/mediator.py, core/memory/guard.py).

"write:<Type>.<field>" is NOT a grant and is rejected outright. It was
accepted here and checked by no authorize() call anywhere: writes are
authorized per action type, so a policy granting write:Order.total
validated cleanly and permitted nothing. write:<Type>.<field> still
exists as an AUDIT identifier in write_mediator.py, which is a
different thing from a permission and is why the two were confused.
  - "read:<Type>" (no dot) -- Type must be real; the TYPE-level read
    grant gating schema visibility itself (core/ontology/mediator.py).

Anything that doesn't match ANY of these seven patterns is rejected
outright, not silently accepted -- almost certainly a typo of one of
the seven above (e.g. a stray colon, a misspelled prefix), and letting
it through unchecked would just be a DIFFERENT, undetectable version
of the same silent-typo problem this module exists to catch.

Deliberately does NOT check whether a real, valid grant is actually
USED by anything (e.g. a write:Order.total grant nobody's action
mutations ever require) -- that's a genuinely different kind of
question (an unused-permission lint, closer to opinion than
correctness) from "does this grant reference something that exists,"
which is the only thing checked here.
"""

def validate_roles(roles: dict, object_types: dict, action_types: dict, enabled_tools: list[str]) -> None:
    for role_name, role_def in roles.items():
        for grant in role_def.get("allowed_actions", []):
            _validate_one_grant(role_name, grant, object_types, action_types, enabled_tools)


def _validate_one_grant(role_name: str, grant: str, object_types: dict, action_types: dict,
                         enabled_tools: list[str]) -> None:
    if grant == "manage:users":
        return

    if grant == "discover:action_types":
        return

    if grant == "manage:deployment":
        # Reloading configuration while running. A SEPARATE grant from
        # manage:users, deliberately: creating an account and replacing
        # the ontology, the grants and the silo wiring are different
        # powers, and a deployment should be able to hand out one
        # without the other.
        return

    if grant.startswith("execute:"):
        action_name = grant.removeprefix("execute:")
        if action_name not in action_types:
            raise ValueError(f"Role {role_name!r}: grant {grant!r} references unknown action type {action_name!r}.")
        return

    if grant.startswith("tool:"):
        tool_name = grant.removeprefix("tool:")
        if tool_name not in enabled_tools:
            raise ValueError(
                f"Role {role_name!r}: grant {grant!r} references a tool not in config.yaml's enabled list."
            )
        return

    if grant.startswith("write:"):
        # REMOVED as a valid grant, not merely unenforced. No
        # authorize() call anywhere checked it -- writes are authorized
        # by "execute:<ActionType>" -- so a policy granting
        # write:Order.total validated cleanly and authorized nothing.
        # Rejecting it with the real alternative is better than
        # accepting a no-op that reads as a permission.
        raise ValueError(
            f"Role {role_name!r}: grant {grant!r} uses the 'write:' prefix, which is not "
            f"enforced anywhere. Writes are authorized per action type -- use "
            f"'execute:<ActionType>' instead."
        )

    if grant.startswith("read:"):
        _validate_type_or_field_grant(role_name, grant, object_types)
        return

    # See this module's own docstring for the full, real set of six.
    raise ValueError(f"Role {role_name!r}: grant {grant!r} doesn't match any recognized pattern.")


def _validate_type_or_field_grant(role_name: str, grant: str, object_types: dict) -> None:
    # Only "read:" reaches here now that "write:" is rejected upstream,
    # so the prefix itself carries no information worth keeping.
    _, _, rest = grant.partition(":")
    # rest is EITHER "<Type>" (read: only -- the type-level grant) or
    # "<Type>.<field>" -- split on the FIRST "." specifically, since a
    # field name itself is never expected to contain one.
    object_type, sep, field_name = rest.partition(".")

    if object_type not in object_types:
        raise ValueError(f"Role {role_name!r}: grant {grant!r} references unknown type {object_type!r}.")

    if not sep:
        # "read:<Type>" with no field -- fine, the type-level grant.
        return

    valid_field_names = _valid_field_names(object_types[object_type])
    if field_name not in valid_field_names:
        raise ValueError(
            f"Role {role_name!r}: grant {grant!r} references unknown field {field_name!r} on {object_type!r}."
        )


def _valid_field_names(type_schema: dict) -> set[str]:
    # id_field is a real, addressable field (read:<Type>.<id_field> is
    # a completely ordinary, common grant throughout this project's
    # own real deployments) even though it isn't listed under the
    # type's own "fields" -- see core/deployment_loader.py's own
    # schema handling for why. Matches core/ontology/action_types.py's
    # own, identical reasoning for mutation property names.
    return set(type_schema["fields"]) | {type_schema["id_field"]}
