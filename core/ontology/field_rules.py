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

RULES ACROSS ROWS -- FUNCTIONAL DEPENDENCIES -- were added on 13 October:

    object_types:
      Customer:
        dependencies:
          city_follows_zip:
            determinant: [zip]          # one field or several
            dependent: city
            on_violation: quarantine    # warn (default) | quarantine | fail

"Rows that agree on the zip agree on the city." The precedent is the
data-cleaning literature's own starting point: a functional dependency
is the simplest DENIAL CONSTRAINT, and HoloClean and its predecessors
detect violations of exactly this form before anything subtler.
Checked in SILVER ONLY, over the whole table after the per-row rules:
a write would need a scan of every other row to check, and the source
is where the conflicting row lives.

WHICH ROWS A QUARANTINE HOLDS. A violating group has no row that is
known wrong. When one dependent value holds a STRICT MAJORITY of the
group, the rows disagreeing with it are held and the reason names the
majority; with no majority, every row of the group is held. The first
is what a person would do; the second refuses to guess.

GENERAL DENIAL CONSTRAINTS ARE NOT BUILT, deliberately: "no two rows
where A < A' and B > B'" needs an expression language over pairs of
rows, the free-form route the owner declined for derived fields (R37).
A functional dependency is the case asked for by name.

BOTH FIELDS IN ONE STORAGE, refused at load otherwise: silver checks a
source row, and a rule spanning two sources has no single row to check.
"""

import operator
from dataclasses import dataclass

from core.ontology.constraints import _comparable, _data_type
from core.ontology.field_types import is_computed

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


# -- functional dependencies (R29, across rows) -----------------------------

_DEPENDENCY_KEYS = frozenset({"determinant", "dependent", "on_violation"})


@dataclass(frozen=True)
class FieldDependency:
    name: str
    determinant: tuple
    dependent: str
    policy: str = "warn"

    def describe(self) -> str:
        return f"{', '.join(self.determinant)} determines {self.dependent}"


def dependencies_for(type_def) -> list[FieldDependency]:
    """A type's declared functional dependencies. Unvalidated: load
    calls validate_dependencies first."""
    found = []
    for name, declared in (type_def.get("dependencies") or {}).items():
        determinant = declared["determinant"]
        if isinstance(determinant, str):
            determinant = [determinant]
        found.append(FieldDependency(name, tuple(determinant), declared["dependent"],
                                     declared.get("on_violation", "warn")))
    return found


def validate_dependencies(object_types) -> None:
    """Refuses, at load, a dependency that could never be checked."""
    for type_name, type_def in object_types.items():
        declared = type_def.get("dependencies")
        if declared is None:
            continue
        if not hasattr(declared, "items"):
            raise ValueError(f"{type_name}: `dependencies` must be a mapping of named rules.")
        fields = type_def.get("fields") or {}
        for name, rule in declared.items():
            where = f"{type_name} dependency {name!r}"
            if not hasattr(rule, "get"):
                raise ValueError(f"{where} must be a mapping with determinant and dependent.")
            unknown = sorted(set(rule) - _DEPENDENCY_KEYS)
            if unknown:
                raise ValueError(f"{where}: unknown key(s) {unknown}; known: "
                                 f"{sorted(_DEPENDENCY_KEYS)}.")
            determinant = rule.get("determinant")
            if isinstance(determinant, str):
                determinant = [determinant]
            if not determinant or not isinstance(determinant, (list, tuple)):
                raise ValueError(f"{where}: `determinant` must name one field or a list.")
            named = [*determinant, rule.get("dependent")]
            for field_name in named:
                if field_name not in fields:
                    raise ValueError(f"{where} names {field_name!r}, which {type_name} "
                                     f"does not have.")
                if fields[field_name].get("type") == "link" or is_computed(fields[field_name]):
                    raise ValueError(f"{where}: {field_name!r} is not a stored value; a "
                                     f"dependency is checked on source rows.")
            if rule["dependent"] in determinant:
                raise ValueError(f"{where}: {rule['dependent']!r} cannot determine itself.")
            if len({fields[field_name].get("storage") for field_name in named}) != 1:
                raise ValueError(f"{where}: its fields live in different storages, so no "
                                 f"single source table holds them all.")
            if rule.get("on_violation", "warn") not in _POLICIES:
                raise ValueError(f"{where}: `on_violation` must be one of {list(_POLICIES)}.")


def dependency_violations(dependency: FieldDependency, rows, columns) -> "dict[int, str]":
    """{row index: why it breaks the dependency}. `columns` maps field
    names to the row's column names. Rows with an empty determinant are
    not grouped -- an unknown zip agrees with nothing -- and an empty
    dependent is not a disagreement: whether it may be empty is
    `required`'s question, as for every rule here."""
    groups: dict[tuple, list[int]] = {}
    for index, row in enumerate(rows):
        key = tuple(row.get(columns[name]) for name in dependency.determinant)
        if any(part is None for part in key):
            continue
        if row.get(columns[dependency.dependent]) is None:
            continue
        groups.setdefault(key, []).append(index)
    found: dict[int, str] = {}
    for key, members in groups.items():
        counts: dict = {}
        for index in members:
            value = rows[index].get(columns[dependency.dependent])
            counts[value] = counts.get(value, 0) + 1
        if len(counts) < 2:
            continue
        shown = ", ".join(repr(part) for part in key)
        values = ", ".join(repr(value) for value in sorted(counts, key=repr))
        majority = max(counts, key=lambda value: counts[value])
        if counts[majority] * 2 > len(members):
            for index in members:
                value = rows[index].get(columns[dependency.dependent])
                if value != majority:
                    found[index] = (f"breaks {dependency.name!r}: {dependency.describe()}, and "
                                    f"{shown} has {dependency.dependent} {majority!r} in "
                                    f"{counts[majority]} of {len(members)} rows, not {value!r}")
        else:
            for index in members:
                found[index] = (f"breaks {dependency.name!r}: {dependency.describe()}, and "
                                f"{shown} has no single {dependency.dependent} ({values})")
    return found
