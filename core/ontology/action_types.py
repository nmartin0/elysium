"""
action_types.py  (schema-load-time validation for action_types)

Every action_type is REQUIRED to use the sub_writes shape -- there is
no supported "flat," single-object shorthand anymore (see propose_
action()'s own docstring for the full reasoning: the object(s) an
action touches are always just ordinary parameters, matching Palantir
Foundry's own model directly). An action_type missing "sub_writes"
entirely is REJECTED here, loudly, at load time -- see this module's
own AI-notes at the bottom for the real, concrete gap this closes: the
old version of this module silently SKIPPED validating an action_type
missing sub_writes (treating it as "the old, deliberately-untouched
shape"), even though propose_action() itself does a bare
action_def["sub_writes"] dict access with no fallback -- meaning a
malformed action_type used to pass schema-load validation cleanly and
then crash with a raw, confusing KeyError the first time anyone
actually proposed it. Found while auditing this file for exactly this
class of gap, not hypothetically.

WHY schema-load time, not propose_action() time: every one of these
checks depends only on the SCHEMA itself (object_type/field names,
declared affected_object_types, the sub_writes list's own shape) --
never on a real caller's parameters, which don't exist yet at load
time. Failing loudly here, once, at startup, is strictly better than
failing lazily, per-request, the first time some caller happens to
propose this specific action -- a malformed action_type is a
deployment-configuration bug, not a runtime condition, and deserves
to be caught before the deployment ever starts serving requests. Same
"fail loudly at load time" discipline used elsewhere in this project
(e.g. core/user_directory.py's UserDirectory.create_user() rejecting
an unknown role_name immediately, not silently).

Each sub_write's own mutations are checked against the target
object_type's REAL, declared fields (plus its own id_field, settable
by a create's own mutations even though it isn't listed under
"fields" itself -- see core/deployment_loader.py's own schema
handling) -- a typo'd property name (e.g. "nmae" instead of "name")
used to pass silently at load time and only surface the first time a
real caller happened to trigger that specific action, the exact same
class of gap the missing-sub_writes case above closes, just one level
deeper.

A SEPARATE, later check still exists at propose_action() time and is
NOT replaced by this: two sub_writes with DIFFERENT object_id
EXPRESSIONS (e.g. parameter.from_account_id and parameter.
to_account_id) could still resolve to the SAME real id once real
parameters arrive (a caller could legitimately, if unusually, supply
the same account for both). This module only catches the WEAKER,
purely structural case -- the literal SAME expression string used
twice, which is guaranteed to collide no matter what parameters ever
arrive, and is therefore safe to reject at load time, before any
request exists. The full check, against REAL resolved ids, belongs
at propose_action() time and is a separate, later piece of work.

MAX_SUB_WRITES exists for the same reason Palantir caps their own
batched action calls (10,000, at their scale) -- holding N locks for
N sequential round-trips has a real, growing latency/contention cost.
Elysium's actual use cases (a transfer, a multi-line-item order, a
reassignment cascade) are small; 20 is deliberately conservative --
a real ceiling a schema author should reconsider their design against
hitting, not a number generous enough to hide an operational problem.
A hard-coded constant, never schema-configurable, never visible to
the model -- sub_writes is entirely schema-authored, the same as
mutations already is; there is no code path where a model composes
one.

object_reference PARAMETERS -- {type: "object_reference",
object_type: "Author"} -- matches Palantir Foundry's own action
parameter model directly (verified against their docs, not assumed:
"Modify object(s): can be used to modify an existing object whose
primary key is derived from object reference parameters" -- the
object being acted on is ALWAYS just a parameter, never a separate,
out-of-band field, at every scale Palantir itself supports). A
sub_write's object_id, when it's a "parameter.<name>" expression,
MUST reference a parameter declared this way, with its own object_type
matching the sub_write's own -- this is what let a later increment
retire the separate, caller-supplied object_id argument entirely
(now done -- see propose_action()'s own docstring): every action,
including ones touching only one object, identifies that object as an
ordinary, named parameter like any other, not a special case.

object_id is NOT required to be a "parameter.<name>" expression at
all -- it uses the exact same resolution vocabulary
_resolve_mutation_value() already gives mutation values (literal,
parameter.<name>, user.security_value), and this module only adds a
check for the one kind (parameter.<name>) that has something
additional to validate against (a declared parameter's own type and
object_type). A literal or user.security_value object_id is
structurally fine and simply has nothing further this module can
check about it at load time.
"""

MAX_SUB_WRITES = 20


def validate_action_types(action_types: dict, object_types: dict) -> None:
    for action_type_name, action_def in action_types.items():
        if "sub_writes" not in action_def:
            raise ValueError(
                f"Action type {action_type_name!r} has no 'sub_writes' -- this is "
                f"required for every action_type now, there is no supported flat, "
                f"single-object shorthand. See this module's own docstring for why "
                f"this used to be silently skipped instead of rejected, and what "
                f"that gap actually let through."
            )
        _validate_sub_writes_action(action_type_name, action_def, object_types)


def _validate_sub_writes_action(action_type_name: str, action_def: dict, object_types: dict) -> None:
    sub_writes = action_def["sub_writes"]
    if not isinstance(sub_writes, list) or not sub_writes:
        raise ValueError(
            f"Action type {action_type_name!r}: sub_writes must be a non-empty list"
        )
    if len(sub_writes) > MAX_SUB_WRITES:
        raise ValueError(
            f"Action type {action_type_name!r}: {len(sub_writes)} sub_writes exceeds "
            f"the maximum of {MAX_SUB_WRITES} -- see this module's own docstring for why "
            f"this is a hard, non-configurable ceiling, not a default to raise."
        )

    declared_types = action_def.get("affected_object_types")
    if not isinstance(declared_types, list) or not declared_types:
        raise ValueError(
            f"Action type {action_type_name!r}: affected_object_types is required "
            f"whenever sub_writes is used, and must be a non-empty list."
        )
    unknown_declared = [t for t in declared_types if t not in object_types]
    if unknown_declared:
        raise ValueError(
            f"Action type {action_type_name!r}: affected_object_types names "
            f"unknown object type(s) {unknown_declared} -- not declared anywhere "
            f"in this deployment's own ontology_schema.yaml."
        )

    declared_params = action_def.get("parameters", {})
    _validate_object_reference_parameters(action_type_name, declared_params, object_types)

    referenced_types: set[str] = set()
    seen_object_refs: set[tuple[str, str]] = set()
    for i, sub_write in enumerate(sub_writes):
        _validate_one_sub_write(action_type_name, i, sub_write, object_types, declared_params)
        object_type = sub_write["object_type"]
        referenced_types.add(object_type)

        # The WEAKER, purely structural duplicate check -- see this
        # module's own docstring for why the full, resolved-id check
        # is a separate, later, propose_action()-time concern.
        object_ref = (object_type, str(sub_write["object_id"]))
        if object_ref in seen_object_refs:
            raise ValueError(
                f"Action type {action_type_name!r}: sub_writes entries {i} and an "
                f"earlier one both reference the IDENTICAL {object_type} "
                f"{sub_write['object_id']!r} -- two sub_writes can never legitimately "
                f"target the exact same object expression; merge their mutations into "
                f"one sub_write instead."
            )
        seen_object_refs.add(object_ref)

    # EXACT match required, not "at least" -- an object_type declared
    # in affected_object_types but never actually referenced by any
    # sub_write is just as much a real drift from what this action
    # type's own reach documentation claims as an UNDER-declared one
    # would be, and is rejected for the identical reason: this
    # declaration is meant to be read, and trusted, by whoever is
    # deciding a role's real reach (see write_mediator.py's own
    # execute: RBAC docstring on why that reach matters) -- a stale,
    # over-broad declaration is exactly as misleading as a missing one.
    over_declared = set(declared_types) - referenced_types
    under_declared = referenced_types - set(declared_types)
    if over_declared or under_declared:
        raise ValueError(
            f"Action type {action_type_name!r}: affected_object_types "
            f"{sorted(declared_types)} does not exactly match the object types its "
            f"own sub_writes actually reference {sorted(referenced_types)} "
            f"(declared but unused: {sorted(over_declared) or 'none'}; "
            f"used but undeclared: {sorted(under_declared) or 'none'})."
        )


def _validate_object_reference_parameters(action_type_name: str, declared_params: dict, object_types: dict) -> None:
    # Applies to EVERY declared object_reference parameter, not just
    # ones actually used as a sub_write's own object_id -- a parameter
    # referencing an object could legitimately be used only inside a
    # mutation's value or a submission_criteria check instead (e.g.
    # "which employee's manager to notify"), and deserves the same
    # "does this object_type actually exist" scrutiny either way.
    for param_name, param_spec in declared_params.items():
        if param_spec.get("type") != "object_reference":
            continue
        referenced_type = param_spec.get("object_type")
        if referenced_type is None:
            raise ValueError(
                f"Action type {action_type_name!r}: parameter {param_name!r} is declared "
                f"type 'object_reference' but has no object_type of its own naming WHICH "
                f"type it refers to."
            )
        if referenced_type not in object_types:
            raise ValueError(
                f"Action type {action_type_name!r}: parameter {param_name!r} references "
                f"unknown object type {referenced_type!r}."
            )


def _validate_one_sub_write(action_type_name: str, index: int, sub_write: dict, object_types: dict,
                             declared_params: dict) -> None:
    required_keys = {"object_type", "object_id", "operation", "mutations"}
    missing = required_keys - sub_write.keys()
    if missing:
        raise ValueError(
            f"Action type {action_type_name!r}: sub_writes[{index}] is missing "
            f"required key(s): {sorted(missing)}"
        )

    object_type = sub_write["object_type"]
    if object_type not in object_types:
        raise ValueError(
            f"Action type {action_type_name!r}: sub_writes[{index}] references "
            f"unknown object type {object_type!r}."
        )

    operation = sub_write["operation"]
    if operation not in ("create", "update"):
        raise ValueError(
            f"Action type {action_type_name!r}: sub_writes[{index}]'s operation must "
            f"be 'create' or 'update', got {operation!r}."
        )

    if not isinstance(sub_write["mutations"], list) or not sub_write["mutations"]:
        raise ValueError(
            f"Action type {action_type_name!r}: sub_writes[{index}].mutations must "
            f"be a non-empty list."
        )

    # Every mutation's own "property" must be a REAL field this
    # object_type actually declares -- catches a typo (e.g. "nmae"
    # instead of "name") that would otherwise pass silently here and
    # only surface as a confusing failure deep inside
    # _group_changes_by_storage() the first time a real caller
    # happened to trigger this specific action. id_field is
    # separately valid too -- it's a real, settable property (a
    # create's own mutations set it explicitly) even though it isn't
    # listed under the type's own "fields" (see core/deployment_
    # loader.py's own schema handling for why).
    valid_properties = set(object_types[object_type]["fields"]) | {object_types[object_type]["id_field"]}
    for mutation_index, mutation in enumerate(sub_write["mutations"]):
        property_name = mutation.get("set", {}).get("property")
        if property_name not in valid_properties:
            raise ValueError(
                f"Action type {action_type_name!r}: sub_writes[{index}].mutations[{mutation_index}] "
                f"sets unknown property {property_name!r} on {object_type!r} -- not declared "
                f"anywhere in this deployment's own ontology_schema.yaml."
            )

    object_id = sub_write["object_id"]
    if isinstance(object_id, str) and object_id.startswith("parameter."):
        # See this module's own docstring for why ONLY this expression
        # kind gets checked here -- literal and user.security_value
        # object_ids are structurally fine, with nothing further to
        # validate against at load time.
        param_name = object_id.removeprefix("parameter.")
        param_spec = declared_params.get(param_name)
        if param_spec is None:
            raise ValueError(
                f"Action type {action_type_name!r}: sub_writes[{index}]'s object_id "
                f"references parameter {param_name!r}, which is not declared in this "
                f"action's own parameters."
            )
        if param_spec.get("type") != "object_reference":
            raise ValueError(
                f"Action type {action_type_name!r}: sub_writes[{index}]'s object_id "
                f"references parameter {param_name!r}, which must be declared "
                f"type 'object_reference' to identify an object, not "
                f"{param_spec.get('type')!r}."
            )
        if param_spec.get("object_type") != object_type:
            raise ValueError(
                f"Action type {action_type_name!r}: sub_writes[{index}]'s object_id "
                f"references parameter {param_name!r}, declared as a reference to "
                f"{param_spec.get('object_type')!r}, but this sub_write's own "
                f"object_type is {object_type!r} -- these must match."
            )


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - This module used to silently SKIP validating any action_type
#   missing "sub_writes" entirely, treating it as "the old, still-
#   supported flat shape." It wasn't -- propose_action() does a bare
#   action_def["sub_writes"] dict access with no fallback, so a
#   malformed action_type used to pass this module's own validation
#   cleanly and then crash with a raw KeyError the first time anyone
#   actually proposed it. NOW FIXED: missing "sub_writes" is rejected
#   loudly here instead. Found while specifically auditing this file
#   for exactly this class of gap (part of a broader pass also
#   covering role-grant validation -- see core/intermediate_layer/
#   policy_validation.py, and mutation-property-name validation,
#   added at the same time, immediately below this note).
# - templates/ontology_schema.yaml -- the file explicitly meant to be
#   copied into new deployments -- was STILL using the old, now-
#   rejected flat shape when this gap was found. Anyone following it
#   would have produced a config that passed validation and crashed
#   on first real use. Migrated to sub_writes, and verified against
#   the REAL validate_action_types() function directly, not just
#   visually inspected. templates/policy.yaml's own explanatory
#   comment had a related, separate gap: it never mentioned write:
#   grants at all (added to this project after that template was
#   originally written) -- also fixed, same pass.
#
# DEFERRED (known, intentional, not yet built):
# - No check that a declared object_reference parameter, or a
#   sub_write's own object_id expression, is genuinely REACHABLE given
#   the action's own declared "parameters" -- e.g. an object_reference
#   parameter that's declared but never referenced by anything at all
#   (not a sub_write's object_id, not a mutation value, not a
#   submission_criteria check) is not currently flagged as suspicious.
#   This would be a "declared but unused" lint, a genuinely different
#   kind of check from "does this reference something real" (the only
#   thing this whole module does today) -- not built here, on purpose,
#   matching this module's own docstring reasoning for why the
#   analogous "is this write: grant actually used" question isn't
#   checked by policy_validation.py either.
