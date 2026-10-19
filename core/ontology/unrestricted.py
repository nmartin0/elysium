"""`security: unrestricted` -- an object type with no row check (19 October).

WHAT IT IS FOR. Some data is nobody's private business: a product
catalogue every salesperson in every region should see. Every type had to
name a security field, and a catalogue has none to name -- the rule was
mechanical (the mediator read `type_schema["security"]` directly, and a
missing block crashed it), not a decision anyone made.

THE PRECEDENT. Foundry's object security policies are optional: without
one, an object type is governed by its ordinary permissions (Viewer on
the type and its data source); with one, the policy overrides those.
Databricks' row filters apply only to tables matching their condition.
So: no row check, and the ROLE CHECK STILL APPLIES -- `read:Product` is
still needed to see a product at all.

THREE RULES, agreed with the owner:

  1. WRITTEN OUT ON PURPOSE. `security: unrestricted`, exactly; a missing
     block is still an error ("nothing is implicit", PRINCIPLES.md). A
     via_field chain may not END at an unrestricted type either, because
     that would make the linking type unrestricted without anyone having
     written so (object_type_validation refuses it).
  2. THE ROLE CHECK STILL APPLIES. Only the per-object comparison of the
     object's value to the user's is skipped -- so a user with no value
     of the security attribute can still see unrestricted objects.
  3. THE LOWEST LABEL, NOT "NO LABEL". SECURITY_ARCHITECTURE.md treats
     security values as compartments; unrestricted is the empty set.
     Reading from it crosses nothing; WRITING INTO it from a labelled
     object is a write-down, and refused -- otherwise an unrestricted
     type is a door for moving restricted values somewhere everyone can
     read them. Foundry warns that object policies do not follow data
     into downstream outputs; this is the part of that Elysium can stop.

THE SENTINEL is a distinct object, never None: None already means "could
not resolve, visible to nobody", and several checks skip None. Code that
must show it to a person or put it in JSON uses `str()`.

IN MEMORY the block is normalised to {"unrestricted": True}, so code that
asks `security.get("field")` gets None rather than crashing on a string;
`is_unrestricted` is how anything asks.
"""

from collections.abc import Mapping

DECLARED = "unrestricted"


class _Unrestricted:
    """The lowest label: the empty set of compartments."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNRESTRICTED"

    def __str__(self) -> str:
        return DECLARED

    def __reduce__(self):
        return (_Unrestricted, ())


UNRESTRICTED = _Unrestricted()


def is_unrestricted(type_def: "Mapping | None") -> bool:
    security = (type_def or {}).get("security") if isinstance(type_def, Mapping) else None
    return isinstance(security, Mapping) and security.get(DECLARED) is True


def normalise_security_blocks(schema_raw: dict) -> dict:
    """`security: unrestricted` -> {"unrestricted": True}, in place, on the
    parsed YAML before anything else reads it. Any OTHER string is left
    for validation to refuse with the type's name."""
    for type_def in (schema_raw.get("object_types") or {}).values():
        if isinstance(type_def, dict) and type_def.get("security") == DECLARED:
            type_def["security"] = {DECLARED: True}
    return schema_raw


def as_stored_compartment(value):
    """A security value as the review stores record a compartment: None
    for an unrestricted record. Those stores already read None as "no
    compartment, shared by everyone who may review" (api/routes.py, the
    recipe and prediction gates); storing the sentinel instead -- or its
    text, "unrestricted" -- would have compared unequal to every
    reviewer's value and hidden the proposal from all of them."""
    return None if value is UNRESTRICTED else value
