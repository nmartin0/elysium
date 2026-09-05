"""
object_type_validation.py  (schema-load-time validation for object
types' own title_field AND security.field/security.via_field)

TITLE_FIELD -- an OPTIONAL, per-object-type declaration of which
field's own value acts as a human-readable display name (see
core/ontology/schema.py's own get_title_field() for the runtime-lookup
counterpart, and README.md's own section 3.3 for the deployer-facing
explanation). Matches Palantir's own "title key" concept directly
(verified against their docs, not assumed: "Title key: The property
that acts as a display name for objects of this type") -- named
title_field here instead to match this project's OWN existing
id_field naming convention, not Palantir's own "key" terminology.

SECURITY.FIELD / SECURITY.VIA_FIELD -- the actual MAC boundary itself
(core/ontology/mediator.py's own _get_security_value()). A real,
previously-honest, previously-DEFERRED gap, closed here: this exact
"typo'd reference fails silently at schema-load time" class of bug
this module already closed for title_field was left open for the
security-critical field specifically, deliberately not fixed as a
side effect of adding title_field support -- see this module's own
git history / previous AI-notes for that original, explicit deferral.
Closed now, on its own, separately-considered pass, precisely because
a config builder is about to make editing this exact file meaningfully
easier for an admin to do, including easier to get subtly wrong.

WHY schema-load time, not runtime: same reasoning as core/ontology/
action_types.py's own module docstring -- a typo'd title_field or
security.field (e.g. "nmae" instead of "name") depends only on the
schema itself, never a real caller's own parameters, and deserves to
fail loudly at startup, not the first time a real object happens to
render, or the first time any MAC check actually needs to resolve it.

THE FOUR REAL GAPS FOUND AND CLOSED HERE, together, not separately --
all discovered by reading core/ontology/mediator.py's own
_get_security_value() directly before writing any of this, not
assumed from the schema format alone:
  1. Every object type's own "security" key was OPTIONAL at
     deployment_loader.py's own parse time (object_type_def.get(
     "security", {})) -- but mediator.py's own _get_security_value()
     does a DIRECT, non-.get() access (type_schema["security"]),
     meaning a missing security block entirely would raise a raw,
     uncontrolled KeyError the first time any MAC check ever touched
     that object type, not a clear error at startup.
  2. security.via_field never even received deployment_loader.py's
     own _require_str() type-coercion check -- security.field did,
     via_field didn't, a real, narrower gap alongside the referential
     one this module otherwise closes.
  3. No referential check that security.field references a real,
     declared, plain "data" field (never "link" -- a link field's own
     value is an id, never a meaningful, comparable security value)
     of the SAME object type -- the exact class of check this module
     already does for title_field, just missing for this one.
  4. No referential check that security.via_field references a real,
     declared "link" field (the OPPOSITE restriction from #3) whose
     own "target" is itself a real object_type -- AND, since
     _get_security_value() resolves a via_field chain RECURSIVELY
     (an object type's own security can point through another type's
     security, transitively), no check that the WHOLE chain actually,
     eventually terminates in a real security.field, with no cycle.
     An unvalidated cycle here would not just fail loudly -- it would
     hang the whole request via infinite recursion, the most severe
     failure shape this whole module exists to prevent.

DELIBERATELY still scoped to these two concerns (title_field,
security.field/via_field) -- id_field itself was considered and
dropped: there is genuinely nothing to validate it against at this
level (it's a declared name the rest of the system treats as
authoritative, not a reference into "fields" the way title_field is)
-- validate_identifier_types() already covers the one thing that IS
checkable about it (that it's a real string). A general link field's
own "target" -- for a link field that ISN'T a security.via_field --
still has no referential validation anywhere in this project; a real,
separate, broader gap, deliberately NOT closed here, matching this
module's own "don't scope-creep into an unrelated, lower-stakes
question" discipline that originally deferred THIS fix in the first
place.
"""

from core.ontology.field_types import FIELD_DATA_TYPES


def validate_object_types(object_types: dict) -> None:
    for object_type_name, type_def in object_types.items():
        _validate_title_field(object_type_name, type_def)
        _validate_security(object_type_name, object_types, visited=frozenset())
        _validate_field_data_types(object_type_name, type_def)


def _validate_field_data_types(object_type_name: str, type_def: dict) -> None:
    # A typo'd data_type must fail HERE, at deployment load, rather
    # than at sync time -- by which point it would be a confusing
    # failure in a scheduled batch job, far from the schema that
    # actually caused it. Same "fail loudly, as early as possible"
    # discipline every other check in this file follows.
    for field_name, field_info in type_def.get("fields", {}).items():
        declared = field_info.get("data_type")
        if declared is None:
            # Genuinely optional -- see core/ontology/field_types.py's
            # own docstring on why every schema predating this stays
            # valid.
            continue
        if declared not in FIELD_DATA_TYPES:
            raise ValueError(
                f"Object type {object_type_name!r}: field {field_name!r} declares unknown "
                f"data_type {declared!r} -- known types: {sorted(FIELD_DATA_TYPES)}."
            )
        if field_info.get("type") == "link":
            # A link field's own value is an id (or a list of them),
            # resolved from the TARGET type's own id column -- its type
            # is that target's business, not this field's to redeclare.
            raise ValueError(
                f"Object type {object_type_name!r}: field {field_name!r} is a link and must not "
                f"declare its own data_type."
            )


def _validate_title_field(object_type_name: str, type_def: dict) -> None:
    title_field = type_def.get("title_field")
    if title_field is None:
        return

    if title_field == type_def.get("id_field"):
        # The id_field itself is a real, valid title_field target --
        # not listed under "fields" at all (see core/ontology/
        # schema.py's own get_column_for_field() docstring for why),
        # but a completely legitimate, if unglamorous, display value
        # in the absence of anything better.
        return

    field_info = type_def.get("fields", {}).get(title_field)
    if field_info is None:
        raise ValueError(f"Object type {object_type_name!r}: title_field references unknown field {title_field!r}.")
    if field_info.get("type") != "data":
        # A link field's own "value" is an id (or list of ids), never
        # a sensible display string -- plain data only.
        raise ValueError(
            f"Object type {object_type_name!r}: title_field {title_field!r} must be a plain data field, "
            f"not a link."
        )


def _validate_security(object_type_name: str, object_types: dict, visited: frozenset[str]) -> None:
    # visited: every object_type_name already walked on THIS specific
    # via_field chain -- passed down explicitly on each recursive
    # call, not a module-level or shared mutable set, so validating
    # object type A's own chain can never leak state into a
    # completely separate, later call validating object type B's.
    if object_type_name in visited:
        chain = " -> ".join([*visited, object_type_name])
        raise ValueError(f"Circular security.via_field chain detected: {chain}.")
    visited = visited | {object_type_name}

    type_def = object_types[object_type_name]
    security = type_def.get("security")
    if security is None:
        # Matches mediator.py's own DIRECT, non-.get() access
        # (type_schema["security"]) -- a missing block here would
        # otherwise surface as a raw, uncontrolled KeyError the first
        # time any MAC check ever touched this object type, not a
        # clear error at startup.
        raise ValueError(f"Object type {object_type_name!r} has no security block declared.")

    has_field = "field" in security
    has_via_field = "via_field" in security
    if has_field and has_via_field:
        # Not a hypothetical concern -- mediator.py's own
        # _get_security_value() checks "field" first and would
        # silently ignore via_field entirely if both were present,
        # exactly the kind of quietly-wrong-role-grant class of
        # mistake this project has consistently refused to allow
        # anywhere else.
        raise ValueError(
            f"Object type {object_type_name!r}: security declares both 'field' and 'via_field' -- "
            f"exactly one is required."
        )
    if not has_field and not has_via_field:
        raise ValueError(
            f"Object type {object_type_name!r}: security declares neither 'field' nor 'via_field' -- "
            f"exactly one is required."
        )

    if has_field:
        field_name = security["field"]
        field_info = type_def.get("fields", {}).get(field_name)
        if field_info is None:
            raise ValueError(
                f"Object type {object_type_name!r}: security.field references unknown field {field_name!r}."
            )
        if field_info.get("type") != "data":
            raise ValueError(
                f"Object type {object_type_name!r}: security.field {field_name!r} must be a plain data "
                f"field, not a link."
            )
        return

    via_field = security["via_field"]
    field_info = type_def.get("fields", {}).get(via_field)
    if field_info is None:
        raise ValueError(
            f"Object type {object_type_name!r}: security.via_field references unknown field {via_field!r}."
        )
    if field_info.get("type") != "link":
        # The opposite restriction from security.field above -- a
        # via_field chain only makes sense against a real link (it's
        # how the chain reaches the NEXT object type at all).
        raise ValueError(
            f"Object type {object_type_name!r}: security.via_field {via_field!r} must be a link field, "
            f"not plain data."
        )

    target_type = field_info.get("target")
    if target_type not in object_types:
        raise ValueError(
            f"Object type {object_type_name!r}: security.via_field {via_field!r} targets unknown object "
            f"type {target_type!r}."
        )

    # Recurse -- the chain must eventually terminate in a real
    # security.field, through however many via_field hops. visited
    # (passed explicitly, not shared) is what makes a genuine cycle
    # fail loudly here, at schema-load time, instead of hanging a
    # real request via infinite recursion in mediator.py's own,
    # identically-shaped runtime resolution.
    _validate_security(target_type, object_types, visited)


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - security.field/security.via_field referential validation -- see
#   this module's own docstring for the full, four-part gap this
#   closed and why each part was found by reading mediator.py's own
#   _get_security_value() directly, not assumed from the schema
#   format. Closed as its own, separately-considered pass, exactly as
#   originally, explicitly deferred to be -- not scope creep from an
#   unrelated feature, prompted directly by the config builder about
#   to make editing this exact file meaningfully easier to get wrong.
#
# DEFERRED (known, intentional, not yet built):
# - id_field itself was considered for this module too and dropped:
#   there is genuinely nothing to validate it against at this level
#   (it's a declared name the rest of the system treats as
#   authoritative, not a reference into "fields" the way title_field
#   is) -- validate_identifier_types() already covers the one thing
#   that IS checkable about it (that it's a real string).
# - A general link field's own "target" -- for a link field that is
#   NOT a security.via_field -- still has no referential validation
#   anywhere in this project. A real, separate, broader gap; not
#   closed here, matching this module's own discipline against scope
#   creep from an unrelated, lower-stakes question. Worth its own,
#   separately-considered pass if it's ever actually observed to bite.
