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

default_to_current_object -- an OPTIONAL, per-parameter marker on an
object_reference parameter, e.g. {type: "object_reference",
object_type: "Account", default_to_current_object: true} -- confirmed
directly against Palantir Foundry's own documented mechanism for
exactly this case before designing it (their Action-widget "Default
value" -> "Environment variable" -> "Current object" binding, set on
ONE specific parameter by its own unique ID, not inferred from type).
A REAL, previously-discovered gap this closes: ui/'s own ActionForm.
jsx used to pre-fill and lock EVERY object_reference parameter whose
own object_type happened to match the object type of the page the
form was opened from -- correct for an action with only one such
parameter, but silently wrong the moment two object_reference
parameters share the SAME object_type. The real, live TransferFunds
case is exactly this: from_account_id AND to_account_id both
reference Account -- before this marker existed, BOTH got pre-filled
and locked to the SAME current account's id, with no way to specify a
different "to" account through the form at all. Explicit, by
parameter identity, exactly matching Palantir's own model, never
inferred from object_type alone -- see this module's own validation
below for the three things checked about it: only valid on an
object_reference parameter; a real boolean, not some other YAML-
coercible value; at most one such parameter per action_type (never
more than one "the" current object); and its own object_type must be
a member of affected_object_types (otherwise it could never actually
take effect -- ui/'s own ObjectDetailPanel.jsx only ever offers an
action as a button when the CURRENT page's object_type is a member of
that action's own affected_object_types, so a marked parameter whose
type isn't even in that list could never be "the current object" on
any page this action is reachable from).
"""

MAX_SUB_WRITES = 20


def validate_action_types(action_types: dict, object_types: dict) -> None:
    for action_type_name, action_def in action_types.items():
        if "sub_writes" not in action_def:
            # See this module's own docstring for the full history of
            # why this used to be silently skipped instead of rejected.
            raise ValueError(f"Action type {action_type_name!r}: missing required key 'sub_writes'.")
        _validate_sub_writes_action(action_type_name, action_def, object_types)
        _validate_auto_execute(action_type_name, action_def)
        _validate_parameters_are_used(action_type_name, action_def)


def _validate_sub_writes_action(action_type_name: str, action_def: dict, object_types: dict) -> None:
    sub_writes = action_def["sub_writes"]
    if not isinstance(sub_writes, list) or not sub_writes:
        raise ValueError(f"Action type {action_type_name!r}: 'sub_writes' must be a non-empty list.")
    if len(sub_writes) > MAX_SUB_WRITES:
        # See this module's own docstring for why this is a hard,
        # non-configurable ceiling, not a default to raise.
        raise ValueError(
            f"Action type {action_type_name!r}: {len(sub_writes)} sub_writes exceeds max of {MAX_SUB_WRITES}."
        )

    declared_types = action_def.get("affected_object_types")
    if not isinstance(declared_types, list) or not declared_types:
        raise ValueError(f"Action type {action_type_name!r}: 'affected_object_types' must be a non-empty list.")
    unknown_declared = [t for t in declared_types if t not in object_types]
    if unknown_declared:
        raise ValueError(
            f"Action type {action_type_name!r}: affected_object_types has unknown type(s) {unknown_declared}."
        )

    declared_params = action_def.get("parameters", {})
    _validate_parameter_display_metadata(action_type_name, declared_params)
    _validate_object_reference_parameters(action_type_name, declared_params, object_types, declared_types)

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
                f"Action type {action_type_name!r}: sub_writes[{i}] duplicates an earlier "
                f"reference to {object_type} {sub_write['object_id']!r} -- merge into one sub_write."
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
            f"Action type {action_type_name!r}: affected_object_types doesn't match sub_writes' own "
            f"types (unused: {sorted(over_declared) or 'none'}; undeclared: {sorted(under_declared) or 'none'})."
        )


def _validate_object_reference_parameters(action_type_name: str, declared_params: dict, object_types: dict,
                                           affected_object_types: list) -> None:
    # Applies to EVERY declared object_reference parameter, not just
    # ones actually used as a sub_write's own object_id -- a parameter
    # referencing an object could legitimately be used only inside a
    # mutation's value or a submission_criteria check instead (e.g.
    # "which employee's manager to notify"), and deserves the same
    # "does this object_type actually exist" scrutiny either way.
    default_to_current_object_params = []
    for param_name, param_spec in declared_params.items():
        if param_spec.get("type") != "object_reference":
            if "default_to_current_object" in param_spec:
                # A real, previously-possible mistake -- this flag
                # only makes sense on an object_reference parameter
                # (see this function's own docstring on the flag
                # itself, right below); on anything else it would
                # silently do nothing, ever, since ui/'s own
                # ActionForm.jsx only checks it on parameters it has
                # already confirmed are type: object_reference.
                raise ValueError(
                    f"Action type {action_type_name!r}: parameter {param_name!r} declares "
                    f"default_to_current_object but is not type 'object_reference'."
                )
            continue
        referenced_type = param_spec.get("object_type")
        if referenced_type is None:
            raise ValueError(
                f"Action type {action_type_name!r}: parameter {param_name!r} (object_reference) "
                f"is missing 'object_type'."
            )
        if referenced_type not in object_types:
            raise ValueError(
                f"Action type {action_type_name!r}: parameter {param_name!r} references "
                f"unknown type {referenced_type!r}."
            )

        # default_to_current_object -- OPTIONAL, and by PARAMETER
        # IDENTITY, never inferred from object_type alone. The real,
        # previously-discovered gap this closes: ui/'s own ActionForm.
        # jsx used to pre-fill and lock EVERY object_reference
        # parameter whose own object_type happened to match the page
        # it was opened from -- correct for an action with only one
        # such parameter, but silently wrong the moment two
        # object_reference parameters share the SAME object_type (the
        # real, live TransferFunds case: from_account_id AND
        # to_account_id both reference Account -- both used to get
        # locked to the SAME id, with no way to specify a different
        # "to" account at all). Confirmed directly against Palantir's
        # own documented mechanism for exactly this case (Foundry's
        # own Action-widget "Default value" -> "Environment variable"
        # -> "Current object" binding) before designing this: THEIRS
        # is also explicit, by parameter ID, never inferred from type
        # -- this mirrors that directly, at the schema level instead
        # of a separate view-configuration step, since this project
        # has no separate view-config layer of its own.
        if "default_to_current_object" in param_spec:
            value = param_spec["default_to_current_object"]
            if not isinstance(value, bool):
                # Same "YAML-coercible surprise" concern _require_str()
                # exists for elsewhere in this project (e.g. a bare
                # "true"/"false" STRING here would be truthy in Python
                # either way, silently masking a real authoring
                # mistake) -- caught here, explicitly, rather than
                # left to a confusing failure far away in ui/.
                raise ValueError(
                    f"Action type {action_type_name!r}: parameter {param_name!r}'s own "
                    f"default_to_current_object must be a real boolean, got {value!r}."
                )
            if value:
                default_to_current_object_params.append(param_name)
                if referenced_type not in affected_object_types:
                    # Otherwise this marker could never actually take
                    # effect in real use: ObjectDetailPanel.jsx only
                    # ever offers an action as a button when the
                    # CURRENT page's own object_type is a member of
                    # that action's own affected_object_types -- a
                    # marked parameter whose type isn't even in that
                    # list could never be "the current object" on any
                    # page this action is ever actually reachable
                    # from.
                    raise ValueError(
                        f"Action type {action_type_name!r}: parameter {param_name!r}'s own "
                        f"default_to_current_object references {referenced_type!r}, which is not in "
                        f"affected_object_types -- it could never actually be the current object on any "
                        f"page this action is reachable from."
                    )

    if len(default_to_current_object_params) > 1:
        # Exactly one, or none -- never more than one. Matches
        # Palantir's own model directly: their binding names ONE
        # specific parameter by its own unique ID, never several at
        # once -- two parameters both claiming to be "the current
        # object" is exactly the same class of ambiguity this whole
        # mechanism exists to close, just reintroduced a different way.
        raise ValueError(
            f"Action type {action_type_name!r}: more than one parameter declares "
            f"default_to_current_object (got {sorted(default_to_current_object_params)}) -- at most one is allowed."
        )


def _validate_parameter_display_metadata(action_type_name: str, declared_params: dict) -> None:
    """Checks the optional display_name and description on parameters.

    Object types and fields gained these earlier; action parameters did
    not, which left the one place they matter MOST without them. A
    parameter is what a person is asked to fill in and what the model
    is asked to supply, and "new_from_balance" tells neither of them
    what it is for.

    Optional, and validated the same way the others are: a declared
    value must be a real, non-empty string. An empty display_name is
    worse than none, because it renders blank instead of falling back
    to something readable.
    """
    for param_name, param_def in (declared_params or {}).items():
        if not isinstance(param_def, dict):
            continue
        for key in ("display_name", "description"):
            if key not in param_def:
                continue
            value = param_def[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Action type {action_type_name!r}: parameter {param_name!r} {key} "
                    f"must be a non-empty string, got {value!r}"
                )


PARAMETER_PREFIX = "parameter."


def _collect_parameter_references(action_def: dict) -> set[str]:
    """Every parameter an action actually USES.

    A reference is a string beginning "parameter." -- the only form
    WriteMediator._resolve_mutation_value() expands. Anything else is a
    literal, which is exactly the failure this collection exists to
    expose.
    """
    referenced: set[str] = set()

    def note(value) -> None:
        if isinstance(value, str) and value.startswith(PARAMETER_PREFIX):
            referenced.add(value[len(PARAMETER_PREFIX):])

    for sub_write in action_def.get("sub_writes") or []:
        note(sub_write.get("object_id"))
        for mutation in sub_write.get("mutations") or []:
            note((mutation.get("set") or {}).get("value"))
    for criterion in action_def.get("submission_criteria") or []:
        for value in (criterion or {}).values():
            note(value)
    return referenced


def _validate_parameters_are_used(action_type_name: str, action_def: dict) -> None:
    """Every declared parameter must be referenced somewhere.

    A DIFFERENT check from "does this reference something real", which
    already existed. That one catches a reference to a parameter that
    was never declared; this catches a parameter that was declared and
    never referenced -- and the two fail in opposite directions.

    The failure it exists for is a malformed reference. Writing
    `object_id: $report_id` instead of `parameter.report_id` leaves the
    string as a LITERAL, so the action targets an object whose id is
    the characters "$report_id" and the declared parameter goes
    unused. Nothing else notices: the schema is structurally valid,
    the parameter resolves against nothing, and the action is simply
    wrong at run time.

    That is not hypothetical -- it was written into templates/ by hand
    in an earlier commit here and shipped, and this check is what found
    it.
    """
    declared = set((action_def.get("parameters") or {}).keys())
    referenced = _collect_parameter_references(action_def)

    unused = declared - referenced
    if unused:
        raise ValueError(
            f"Action type {action_type_name!r}: parameter(s) {sorted(unused)} are declared "
            f"but never referenced. A reference must be written 'parameter.<name>'; any "
            f"other form is treated as a literal value."
        )


def _validate_auto_execute(action_type_name: str, action_def: dict) -> None:
    """Checks the optional auto_execute flag.

    Foundry's own Action tool "can be configured to run automatically
    or to run after confirmation from the user", and their governance
    model puts that decision in the ACTION config -- "controls which
    business mutations the agent can perform, and whether confirmation
    is required". Per action type, not a global switch: a deployment
    should be able to let an agent file a low-stakes note without also
    letting it move money unattended.

    Absent means False. The default is confirmation, and it is enforced
    in Python at the point of execution rather than by asking the model
    to behave -- a prompt can be talked around, a branch cannot.
    """
    if "auto_execute" not in action_def:
        return
    value = action_def["auto_execute"]
    if not isinstance(value, bool):
        raise ValueError(
            f"Action type {action_type_name!r}: auto_execute must be true or false, "
            f"got {value!r}."
        )


def _validate_one_sub_write(action_type_name: str, index: int, sub_write: dict, object_types: dict,
                             declared_params: dict) -> None:
    # A delete has nothing to mutate -- it records the object's removal
    # from the ontology, not a change to its values -- so `mutations` is
    # required for create and update only. Declaring an empty list is
    # still accepted, so an author who writes one is not corrected for
    # no reason.
    required_keys = {"object_type", "object_id", "operation"}
    if sub_write.get("operation") != "delete":
        required_keys.add("mutations")
    missing = required_keys - sub_write.keys()
    if missing:
        raise ValueError(f"Action type {action_type_name!r}: sub_writes[{index}] missing key(s) {sorted(missing)}.")

    object_type = sub_write["object_type"]
    if object_type not in object_types:
        raise ValueError(
            f"Action type {action_type_name!r}: sub_writes[{index}] references unknown type {object_type!r}."
        )

    operation = sub_write["operation"]
    if operation not in ("create", "update", "delete"):
        raise ValueError(
            f"Action type {action_type_name!r}: sub_writes[{index}].operation must be "
            f"'create', 'update' or 'delete', got {operation!r}."
        )

    if operation == "delete":
        # Nothing further to check: a delete names an object, not a
        # change to it. An empty mutations list is accepted here rather
        # than rejected, since an author who writes one has expressed
        # exactly what a delete means.
        if sub_write.get("mutations"):
            raise ValueError(
                f"Action type {action_type_name!r}: sub_writes[{index}] is a delete and "
                f"must not declare mutations."
            )
        return

    if not isinstance(sub_write["mutations"], list) or not sub_write["mutations"]:
        raise ValueError(f"Action type {action_type_name!r}: sub_writes[{index}].mutations must be a non-empty list.")

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
                f"sets unknown property {property_name!r} on {object_type!r}."
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
                f"Action type {action_type_name!r}: sub_writes[{index}].object_id references "
                f"undeclared parameter {param_name!r}."
            )
        if param_spec.get("type") != "object_reference":
            raise ValueError(
                f"Action type {action_type_name!r}: sub_writes[{index}].object_id's parameter "
                f"{param_name!r} must be type 'object_reference', got {param_spec.get('type')!r}."
            )
        if param_spec.get("object_type") != object_type:
            raise ValueError(
                f"Action type {action_type_name!r}: sub_writes[{index}].object_id's parameter "
                f"{param_name!r} references {param_spec.get('object_type')!r}, expected {object_type!r}."
            )
