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


def validate_role_coherence(roles: dict) -> None:
    """Checks that hold BETWEEN a role's grants, not within one.

    SEPARATE FROM validate_roles() BY NECESSITY, not taste.
    scripts/lint_deployment.py calls that function once per GRANT --
    handing it a role holding exactly one -- so that one bad grant
    never stops the next from being reported. A cross-grant rule placed
    inside it would see a single grant every time and call every field
    grant orphaned.

    That per-grant call is documented there as safe because the checks
    "are already entirely self-contained per role (verified directly:
    neither compares across different entries)". This is the first rule
    that is not, so it lives outside rather than quietly invalidating
    the observation.
    """
    for role_name, role_def in roles.items():
        _validate_field_grants_have_their_type(
            role_name, set(role_def.get("allowed_actions", [])),
        )


def _validate_field_grants_have_their_type(role_name: str, granted: set) -> None:
    """A field grant is meaningless without a grant on its type.

    Grants were independent strings, so `read:Customer.email` could be
    held WITHOUT any grant on Customer -- a role authorised to read a
    field of a type it cannot even discover. Verified against
    authorize() before this was written: it returned True for the field
    and False for the type.

    Nothing enforced it because nothing looked at two grants together;
    every other check in this module reads one string at a time.

    ANY RUNG SATISFIES IT. read:Customer.email needs Customer to be
    discoverable, not readable -- and `read:` implies `discover:`, so a
    deployment writing the ordinary form is already covered. Verified
    that all three shipped policies pass unchanged.
    """
    for grant in sorted(granted):
        prefix, _, target = grant.partition(":")
        if prefix not in ("read", "discover") or "." not in target:
            continue
        object_type = target.split(".", 1)[0]
        if f"read:{object_type}" in granted or f"discover:{object_type}" in granted:
            continue
        raise ValueError(
            f"Role {role_name!r}: grant {grant!r} names a field of {object_type!r}, but "
            f"the role has no grant on {object_type!r} itself. A field cannot be read "
            f"or discovered on a type the role cannot see -- add "
            f"'discover:{object_type}' or 'read:{object_type}'."
        )


# THE GRANTS THAT ARE EXACT LITERALS, in the order an editor lists them.
EXACT_GRANTS = (
    "manage:users",
    "manage:roles",
    "manage:escalation",
    "manage:deployment",
    "discover:action_types",
)


def grantable(object_types: dict, action_types: dict, enabled_tools: list[str]) -> list[str]:
    """Every grant a role in this deployment could hold.

    DERIVED FROM THE ONTOLOGY, not listed, so it cannot fall behind it:
    a new object type, field, action or tool appears here the moment it
    is declared. The role editor offers exactly this list.

    BESIDE THE VALIDATOR ON PURPOSE, and a test holds them together --
    every grant listed here must pass `_validate_one_grant`. An editor
    offering a grant the validator refuses would let somebody build a
    role that cannot be saved.
    """
    grants = list(EXACT_GRANTS)
    grants += [f"execute:{name}" for name in sorted(action_types)]
    grants += [f"tool:{name}" for name in sorted(enabled_tools)]
    for type_name in sorted(object_types):
        # THE VALIDATOR'S OWN NOTION OF A FIELD, not a second one. A
        # first version read `fields` alone and missed the id_field --
        # so an editor built on it could not grant `read:Customer.
        # customer_id`, which real roles hold. A test comparing this
        # list with the shipped policy caught it.
        fields = sorted(_valid_field_names(object_types[type_name]))
        for verb in ("read", "discover"):
            grants.append(f"{verb}:{type_name}")
            grants += [f"{verb}:{type_name}.{field}" for field in fields]
    return grants


def _validate_one_grant(role_name: str, grant: str, object_types: dict, action_types: dict,
                         enabled_tools: list[str]) -> None:
    if grant == "manage:users":
        return

    if grant == "discover:action_types":
        return

    if grant == "manage:escalation":
        # ADDING A GRANT TO A ROLE THAT YOU DO NOT HOLD YOURSELF.
        # Kubernetes' `escalate` verb, and for its reason: a role edit
        # may otherwise only add grants its author already holds -- which
        # leaves a brand-new grant (an action just added to the ontology)
        # grantable by NOBODY, and once the role store governs,
        # policy.yaml cannot help. This is the explicit way through.
        return
    if grant == "manage:roles":
        # EDITING WHAT A ROLE MAY DO, while the application runs. A
        # SEPARATE grant from manage:users, following both Foundry --
        # "Manage permissions" is distinct from "Manage membership", and
        # customising roles needs an administrator of its own -- and this
        # file's own precedent for manage:deployment below: different
        # powers, which a deployment should be able to hand out apart.
        #
        # MORE POWERFUL THAN manage:users. Moving somebody between roles
        # is bounded by what the roles already allow; changing a role
        # changes what everybody holding it can do.
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

    if grant.startswith("discover:"):
        # THE MIDDLE RUNG. "You may know this exists, and not what it
        # holds." On a TYPE: it appears in the schema, but it cannot be
        # searched and yields no ids. On a FIELD: the field is named,
        # and its value is withheld.
        #
        # Validated identically to read:, because it names the same
        # things -- a grant referencing an object type or field that
        # does not exist is the same mistake whichever rung it is on.
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
