"""
object_type_validation.py  (schema-load-time validation for object
types' own title_field)

Checks title_field -- an OPTIONAL, per-object-type declaration of
which field's own value acts as a human-readable display name (see
core/ontology/schema.py's own get_title_field() for the runtime-lookup
counterpart, and README.md's own section 8.3 for the deployer-facing
explanation). Matches Palantir's own "title key" concept directly
(verified against their docs, not assumed: "Title key: The property
that acts as a display name for objects of this type") -- named
title_field here instead to match this project's OWN existing
id_field naming convention, not Palantir's own "key" terminology.

WHY schema-load time, not runtime: same reasoning as core/ontology/
action_types.py's own module docstring -- a typo'd title_field (e.g.
"nmae" instead of "name") depends only on the schema itself, never a
real caller's own parameters, and deserves to fail loudly at startup,
not the first time a real object happens to render.

DELIBERATELY SCOPED to title_field alone, not a general "validate
every object_type's own referential fields" pass. Found while adding
this: id_field has nothing real to check against at this level (it's
a declared name, not a reference to something else the schema could
confirm exists); security.field/security.via_field DO have a similar,
real gap -- but security.field specifically touches the actual MAC
boundary and deserves its own, separately-considered validation pass,
not a side effect of adding title_field support. Not silently
ignored -- see this module's own AI-notes for the honest, explicit
deferral.
"""


def validate_object_types(object_types: dict) -> None:
    for object_type_name, type_def in object_types.items():
        title_field = type_def.get("title_field")
        if title_field is None:
            continue

        if title_field == type_def.get("id_field"):
            # The id_field itself is a real, valid title_field target
            # -- not listed under "fields" at all (see core/ontology/
            # schema.py's own get_column_for_field() docstring for
            # why), but a completely legitimate, if unglamorous,
            # display value in the absence of anything better.
            continue

        field_info = type_def.get("fields", {}).get(title_field)
        if field_info is None:
            raise ValueError(
                f"Object type {object_type_name!r}: title_field references unknown field {title_field!r}."
            )
        if field_info.get("type") != "data":
            # A link field's own "value" is an id (or list of ids),
            # never a sensible display string -- plain data only.
            raise ValueError(
                f"Object type {object_type_name!r}: title_field {title_field!r} must be a plain data "
                f"field, not a link."
            )


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# DEFERRED (known, intentional, not yet built):
# - security.field and security.via_field (the MAC boundary itself)
#   have NO referential validation today either -- a typo'd
#   security.field would fail silently at schema-load time, the exact
#   same class of gap this module closes for title_field. Deliberately
#   NOT fixed here, as a side effect of adding title_field support --
#   this touches the actual security boundary and deserves its own,
#   separately-considered pass, not scope creep from an unrelated,
#   lower-stakes feature. A real, honest gap, not an oversight.
# - id_field itself was considered for this module too and dropped:
#   there is genuinely nothing to validate it against at this level
#   (it's a declared name the rest of the system treats as
#   authoritative, not a reference into "fields" the way title_field
#   is) -- validate_identifier_types() already covers the one thing
#   that IS checkable about it (that it's a real string).
