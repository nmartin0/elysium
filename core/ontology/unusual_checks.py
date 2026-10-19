"""Records whose numbers are unusual for their kind (R51): a type's
declaration.

    object_types:
      Transaction:
        unusual:
          numbers: [amount]                 # what may be unusual
          within: [category, currency]      # compared with records sharing these

A number is judged against the records that share its `within` values --
a refund's amount against other refunds' in the same currency -- so a
value that is ordinary for the table but wrong for its kind is found
(core/unusual.py says how, and what was measured choosing it). The
per-field check (R30, core/mirror/outliers.py) asks "is this value
unusual for its column"; this asks "for records like this one".

DECLARED, never inferred, like every check here. NEVER A CLASSIFIED
FIELD on either side: a flag would say something about a classified
value to everyone who sees it (D3). Not the id, not a link, not a
computed field -- each has no kind, or no value of its own.

FLAGS ARE SUGGESTIONS, NEVER CHANGES: nothing in the data is altered,
and a record a person marks "expected" is not flagged again until it
changes.
"""

from collections.abc import Mapping

from core.ontology.classifications import field_classifications
from core.ontology.field_types import is_computed

KEYS = frozenset({"numbers", "within"})
NUMERIC = frozenset({"integer", "number", "decimal"})
#: Kinds are text, yes/no, or a date read as itself; a number is not a
#: kind (every value would be its own group).
KIND_TYPES = frozenset({"string", "boolean", "date"})
MAX_NUMBERS = 10
MAX_WITHIN = 3


def unusual_of(type_def: Mapping) -> "tuple[tuple[str, ...], tuple[str, ...]] | None":
    """(numbers, within), or None for a type with no declaration.
    Unvalidated: load calls validate_unusual_checks first."""
    declared = type_def.get("unusual")
    if not isinstance(declared, Mapping):
        return None
    return tuple(declared.get("numbers") or ()), tuple(declared.get("within") or ())


def validate_unusual_checks(object_types: Mapping) -> None:
    """Refuses, at load, a check that could not be made -- or one that
    would say something about a classified value."""
    for type_name, type_def in object_types.items():
        if "unusual" not in type_def:
            continue
        declared = type_def["unusual"]
        where = f"{type_name}.unusual"
        if not isinstance(declared, Mapping):
            raise ValueError(f"{where} is {{numbers: [...], within: [...]}}.")
        extra = sorted(set(declared) - KEYS)
        if extra:
            raise ValueError(f"{where}: unknown key(s) {extra}.")
        numbers, within = declared.get("numbers"), declared.get("within", [])
        if not isinstance(numbers, list) or not 1 <= len(numbers) <= MAX_NUMBERS:
            raise ValueError(f"{where}: `numbers` names 1 to {MAX_NUMBERS} number fields.")
        if not isinstance(within, list) or len(within) > MAX_WITHIN:
            raise ValueError(f"{where}: `within` names at most {MAX_WITHIN} fields to compare "
                             f"records like for like.")
        if len(set(numbers) | set(within)) != len(numbers) + len(within):
            raise ValueError(f"{where}: a field is named twice.")
        fields = type_def.get("fields") or {}
        for name in [*numbers, *within]:
            _check_field(where, type_def, fields, name)
        for name in numbers:
            if (fields[name].get("data_type") or "string") not in NUMERIC:
                raise ValueError(f"{where}: {name!r} is not a number; `numbers` are what may be "
                                 f"unusual, and only a number can be far from its kind's.")
        for name in within:
            if (fields[name].get("data_type") or "string") not in KIND_TYPES:
                raise ValueError(f"{where}: {name!r} is {fields[name].get('data_type')}; a kind "
                                 f"is text, yes/no or a date -- with numbers, every record would "
                                 f"be a kind of its own.")


def _check_field(where: str, type_def: Mapping, fields: Mapping, name) -> None:
    if not isinstance(name, str) or name not in fields:
        raise ValueError(f"{where}: {name!r} is not a field of this type.")
    if name == type_def.get("id_field"):
        raise ValueError(f"{where}: {name!r} is the id.")
    field = fields[name]
    if field.get("type", "data") != "data" or is_computed(field):
        raise ValueError(f"{where}: {name!r} is a link or computed; name the recorded field.")
    labels = field_classifications(field)
    if labels:
        raise ValueError(f"{where}: {name!r} is classified {sorted(labels)}, and a flag would "
                         f"say something about it to everyone who sees one (D3).")
