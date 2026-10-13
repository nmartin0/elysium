"""Rules between two fields of one object (R29).

    object_types:
      Booking:
        rules:
          ends_after_start:
            field: end_date
            op: ">="
            other: start_date
            on_violation: quarantine      # silver: warn | quarantine | fail

A field's `constraints` judge one value alone; some truths need two --
an end that is not before its start, a discount not above the price, a
shipped quantity not above the ordered one. THE PRECEDENT IS THE
COLUMN-PAIR EXPECTATION: Great Expectations ships
`expect_column_pair_values_A_to_be_greater_than_B`, dbt-utils
`expression_is_true`, both evaluated per row. This is that shape, kept
to a comparison between two DECLARED fields so it can be checked at load
rather than parsed out of an expression string at sync time.

ONE RULE LANGUAGE, TWO PLACES, as field constraints already are:

  A WRITE that breaks a rule is REFUSED, every time, whatever
  `on_violation` says -- Elysium does not write a value it knows is
  wrong into a customer's system. An update is judged on the object AS
  IT WOULD BE: its current values with the change applied.

  SILVER applies `on_violation` to what a SOURCE holds -- warn (the
  default), quarantine, or fail -- because the source's data is the
  source owner's to fix, and the mirror reports it.

A NULL ON EITHER SIDE IS NOT A VIOLATION, the rule constraints.py
states: an absent end date is not an end before the start. Whether a
field may be empty is `required`'s question.

WHAT THIS IS NOT, said so the next reader does not assume it: functional
dependencies (zip code determines city) and general denial constraints
span ROWS, not fields of one row, and need a pass over the table rather
than a check per row. R29 names them; they are not built.

BOTH FIELDS IN ONE STORAGE, refused at load otherwise: silver checks a
source row, and a rule spanning two sources has no single row to check.
"""

import operator
from dataclasses import dataclass

from core.ontology.constraints import _comparable, _data_type

OPERATORS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt,
    ">=": operator.ge, "==": operator.eq, "!=": operator.ne,
}
_ORDERING = frozenset({"<", "<=", ">", ">="})
_ORDERED_TYPES = frozenset({"integer", "number", "decimal", "date", "timestamp", "timestamptz"})
_NUMERIC = frozenset({"integer", "number", "decimal"})
_KEYS = frozenset({"field", "op", "other", "on_violation"})
_POLICIES = ("warn", "quarantine", "fail")


@dataclass(frozen=True)
class FieldRule:
    name: str
    field: str
    op: str
    other: str
    policy: str = "warn"

    def describe(self) -> str:
        return f"{self.field} {self.op} {self.other}"


def rules_for(type_def) -> list[FieldRule]:
    """A type's declared rules, in declaration order. Unvalidated: load
    calls validate_field_rules first."""
    return [
        FieldRule(name=name, field=rule["field"], op=rule["op"], other=rule["other"],
                  policy=rule.get("on_violation", "warn"))
        for name, rule in (type_def.get("rules") or {}).items()
    ]


def _family(data_type: str) -> str:
    """Integers, numbers and decimals compare with one another; every
    other type only with itself."""
    return "numeric" if data_type in _NUMERIC else data_type


def validate_field_rules(object_types) -> None:
    """Refuses a rule that could never be checked, at load."""
    for type_name, type_def in object_types.items():
        declared = type_def.get("rules")
        if declared is None:
            continue
        if not hasattr(declared, "items"):
            raise ValueError(f"{type_name}: `rules` must be a mapping of named rules.")
        fields = type_def.get("fields") or {}
        for name, rule in declared.items():
            where = f"{type_name} rule {name!r}"
            if not hasattr(rule, "get"):
                raise ValueError(f"{where} must be a mapping with field, op and other.")
            unknown = sorted(set(rule) - _KEYS)
            if unknown:
                raise ValueError(f"{where}: unknown key(s) {unknown}; known: {sorted(_KEYS)}.")
            for key in ("field", "other"):
                if rule.get(key) not in fields:
                    raise ValueError(f"{where}: `{key}` names {rule.get(key)!r}, which "
                                     f"{type_name} does not have.")
                if fields[rule[key]].get("type") == "link":
                    raise ValueError(f"{where}: `{key}` names a link; a rule compares values.")
            if rule["field"] == rule["other"]:
                raise ValueError(f"{where} compares {rule['field']!r} with itself.")
            op = rule.get("op")
            if op not in OPERATORS:
                raise ValueError(f"{where}: `op` must be one of {list(OPERATORS)}, got {op!r}.")
            left, right = _data_type(fields[rule["field"]]), _data_type(fields[rule["other"]])
            if _family(left) != _family(right):
                raise ValueError(f"{where} compares a {left} with a {right}.")
            if op in _ORDERING and left not in _ORDERED_TYPES:
                raise ValueError(f"{where}: `{op}` does not apply to {left} fields; "
                                 f"use == or !=.")
            if fields[rule["field"]].get("storage") != fields[rule["other"]].get("storage"):
                raise ValueError(f"{where}: the two fields live in different storages, so no "
                                 f"single source row holds both.")
            if rule.get("on_violation", "warn") not in _POLICIES:
                raise ValueError(f"{where}: `on_violation` must be one of {list(_POLICIES)}.")


def rule_violation(rule: FieldRule, type_def, values) -> "str | None":
    """Why these values break the rule, or None. `values` maps FIELD
    names to values, coerced or raw -- both are compared through the same
    coerce() the constraints use."""
    left, right = values.get(rule.field), values.get(rule.other)
    if left is None or right is None:
        return None
    fields = type_def.get("fields") or {}
    a = _comparable(left, _data_type(fields[rule.field]))
    b = _comparable(right, _data_type(fields[rule.other]))
    if OPERATORS[rule.op](a, b):
        return None
    return f"breaks rule {rule.name!r}: {rule.describe()} ({left!r} against {right!r})"
