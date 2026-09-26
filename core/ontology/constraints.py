"""Constraints on the VALUES a field may hold.

FOUNDRY'S VALUE TYPES are the precedent: "a minimum value, maximum
value, or range of allowed values", a regex "that the string must
match", an enum -- and they "enforce data validation in a manner
reusable across the platform". Declared on the PROPERTY, so every
write to it is checked, not only the ones through one action.

THAT IS WHY THEY LIVE ON THE FIELD HERE. Every write passes through
write_mediator -- the grant algebra's one chokepoint -- so a constraint
declared once is enforced for every action that sets the field.

CHECKED TWICE: at proposal, and again at CONFIRM against the CURRENT
schema. A proposal made before a constraint existed must not slip
through by being approved after it -- the grant algebra's own rule,
"re-evaluated at the point of use".

ONE DELIBERATE DEPARTURE FROM FOUNDRY. Its `range` on a STRING
constrains the string's LENGTH, so `min: 3` would mean different things
on different fields. Here lengths have their own keys, and a key never
changes meaning with the field it is on.

A NULL IS NOT CHECKED. Clearing a field is not a value out of range;
whether a field may be empty is a different question.

WHAT IS NOT CHECKED: data already in a silo. These guard what ELYSIUM
writes. Source data arrives through the mirror, where the owner of the
source decides what is valid.
"""

import re
from decimal import Decimal, InvalidOperation

from core.ontology.field_types import DEFAULT_FIELD_DATA_TYPE, coerce

_ORDERED = {"integer", "number", "decimal", "date", "timestamp", "timestamptz"}
_TEXT = {"string"}
_KEYS = {
    "min": _ORDERED, "max": _ORDERED,
    "min_length": _TEXT, "max_length": _TEXT,
    "pattern": _TEXT,
    # DECLARED, NEVER INFERRED (ZOO-02, ZOO-03, ZOO-04). A field can
    # say that its text must contain nothing invisible; what a
    # violation DOES -- warn, quarantine, refuse -- is the existing
    # policy, so this adds a rule and no new machinery.
    "no_invisible_characters": _TEXT,
    "one_of": None,  # any scalar type
}


def _data_type(field_def: dict) -> str:
    return field_def.get("data_type") or DEFAULT_FIELD_DATA_TYPE


def _comparable(value, data_type: str):
    """A value in the form constraints compare.

    THROUGH THE SAME coerce() THE MIRROR USES, so "49.99" and 49.99 and
    Decimal("49.99") compare as one value -- and a date string compares
    as a date, not lexically, which is the bug 0.5.3 fixed.
    """
    coerced = coerce(value, data_type)
    if data_type == "decimal" and not isinstance(coerced, Decimal):
        coerced = Decimal(str(coerced))
    return coerced


def validate_constraints(object_types: dict) -> None:
    """Refuses a malformed `constraints:` block, at load.

    A MISTAKE HERE STOPS THE DEPLOYMENT STARTING. An unknown key, a
    constraint on a type it cannot apply to, a bound that is not a value
    of the field's type, a minimum above its maximum, a pattern that
    does not compile -- each would otherwise be a constraint that
    silently never fires, or fires on everything.
    """
    for type_name, type_def in object_types.items():
        for field_name, field_def in (type_def.get("fields") or {}).items():
            constraints = field_def.get("constraints")
            if constraints is None:
                continue
            where = f"{type_name}.{field_name}"
            if not isinstance(constraints, dict) or not constraints:
                raise ValueError(f"{where}: `constraints` must be a non-empty mapping.")
            data_type = _data_type(field_def)

            unknown = sorted(set(constraints) - set(_KEYS))
            if unknown:
                raise ValueError(f"{where}: unknown constraint(s) {unknown}; "
                                 f"known: {sorted(_KEYS)}.")
            for key in constraints:
                allowed = _KEYS[key]
                if allowed is not None and data_type not in allowed:
                    raise ValueError(f"{where}: `{key}` does not apply to a "
                                     f"{data_type} field.")

            for key in ("min", "max"):
                if key in constraints:
                    try:
                        _comparable(constraints[key], data_type)
                    except (ValueError, TypeError, InvalidOperation) as e:
                        raise ValueError(f"{where}: `{key}` is not a {data_type}: {e}") from e
            if "min" in constraints and "max" in constraints and (
                _comparable(constraints["min"], data_type)
                > _comparable(constraints["max"], data_type)
            ):
                raise ValueError(f"{where}: `min` is above `max`.")

            for key in ("min_length", "max_length"):
                if key in constraints:
                    bound = constraints[key]
                    if not isinstance(bound, int) or isinstance(bound, bool) or bound < 0:
                        raise ValueError(f"{where}: `{key}` must be a whole number.")
            if constraints.get("min_length", 0) > constraints.get("max_length", float("inf")):
                raise ValueError(f"{where}: `min_length` is above `max_length`.")

            if "pattern" in constraints:
                try:
                    re.compile(constraints["pattern"])
                except (re.error, TypeError) as e:
                    raise ValueError(f"{where}: `pattern` does not compile: {e}") from e

            if "one_of" in constraints:
                options = constraints["one_of"]
                if not isinstance(options, list) or not options:
                    raise ValueError(f"{where}: `one_of` must be a non-empty list.")
                for option in options:
                    try:
                        _comparable(option, data_type)
                    except (ValueError, TypeError, InvalidOperation) as e:
                        raise ValueError(f"{where}: `one_of` holds {option!r}, "
                                         f"which is not a {data_type}: {e}") from e


def violation(field_def: dict, value) -> str | None:
    """Why `value` may not be written to this field, or None.

    THE MESSAGE NAMES THE RULE AND THE VALUE, because the person reading
    it is the one who has to choose a different value.
    """
    constraints = field_def.get("constraints")
    if not constraints or value is None:
        return None
    data_type = _data_type(field_def)
    try:
        comparable = _comparable(value, data_type)
    except (ValueError, TypeError, InvalidOperation):
        return f"{value!r} is not a valid {data_type}."

    if "min" in constraints and comparable < _comparable(constraints["min"], data_type):
        return f"{value!r} is below the minimum of {constraints['min']!r}."
    if "max" in constraints and comparable > _comparable(constraints["max"], data_type):
        return f"{value!r} is above the maximum of {constraints['max']!r}."
    if "min_length" in constraints and len(str(value)) < constraints["min_length"]:
        return f"{value!r} is shorter than {constraints['min_length']} characters."
    if "max_length" in constraints and len(str(value)) > constraints["max_length"]:
        return f"{value!r} is longer than {constraints['max_length']} characters."
    if constraints.get("no_invisible_characters"):
        from core.invisible_text import describe

        hiding = describe(value)
        if hiding is not None:
            return f"{hiding}"
    if "pattern" in constraints and not re.fullmatch(constraints["pattern"], str(value)):
        # FULL MATCH. Foundry lets a pattern pass on a substring as an
        # option; a pattern meant to shape a whole value that passes on
        # any part of it lets almost anything through.
        return f"{value!r} does not match the pattern {constraints['pattern']!r}."
    if "one_of" in constraints and comparable not in {
        _comparable(option, data_type) for option in constraints["one_of"]
    }:
        return f"{value!r} is not one of {constraints['one_of']!r}."
    return None
