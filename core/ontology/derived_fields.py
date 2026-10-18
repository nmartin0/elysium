"""Fields worked out from other fields of the same object (R37).

    object_types:
      Customer:
        fields:
          full_name:
            derived:
              concat: [first_name, last_name]
              separator: " "
          age:
            derived: {years_since: date_of_birth}
      OrderLine:
        fields:
          total:
            derived: {multiply: [quantity, unit_price]}
          with_tax:
            derived: {multiply: [total_before_tax, 1.2]}

A FIXED SET OF FORMULAS, chosen by the owner on 13 October over
free-form expressions: each one is checked when the configuration
loads -- its inputs exist, are the right types, and yield a known type
-- so a derived field is as typed and as validated as a stored one.
Foundry draws the same line: a derived property is a declared
computation over other properties of the same object, not a scripting
hook. Free-form expressions were offered and declined as harder to
check up front and to keep safe.

THE FORMULAS:

    concat: [field, ...]          text; empty inputs skipped with their
      separator: " "              separator; all empty -> empty
    add | subtract | multiply | divide: [a, b]
                                  a field or a number on each side;
                                  dividing by zero -> empty
    days_between: [start, end]    whole days from start to end
    years_since: field            whole years from a date to TODAY
    coalesce: [field, ...]        the first that is not empty

AN EMPTY INPUT MAKES AN EMPTY RESULT for arithmetic and dates, as SQL's
NULL does: 0 for a missing quantity would be a number nobody entered.
concat and coalesce exist precisely to work around missing values, so
they skip them.

WHO MAY READ ONE: someone who may read the derived field AND every
field it is computed from. Otherwise a total would hand out a unit
price to somebody refused the price -- arithmetic undoes a field
grant. core/ontology/mediator.py enforces that where values are read.

WHERE THE VALUE COMES FROM: gold holds it, computed when gold is
published, so filters, sorting and counts work on it like any field.
A read of one object recomputes it from its inputs as they are read,
so a change waiting to sync is reflected in the total beside it.
`years_since` is therefore as of today when an object is read, and as
of the last publication in a filter or count.

NOT HERE, deliberately: a derived field over ANOTHER derived field,
or over a link. Each would be possible; each makes "what does this
depend on" a graph walk rather than a list, and nobody has asked.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from core.ontology.field_types import (
    DECIMAL_SCALE,
    DEFAULT_FIELD_DATA_TYPE,
    coerce,
    is_computed,
    split_declared_type,
)

ARITHMETIC = ("add", "subtract", "multiply", "divide")
FORMULAS = (*ARITHMETIC, "concat", "days_between", "years_since", "coalesce")
_NUMERIC = ("integer", "number", "decimal")
_DATES = ("date", "timestamp", "timestamptz")
#: Keys a derived field may carry beside `derived`. Anything about
#: STORAGE or STORED VALUES is refused: it has no column, and a
#: constraint on a value nobody enters is a constraint on its inputs.
ALLOWED_BESIDE = frozenset({"derived", "display_name", "description", "classification",
                            "classifications", "type", "data_type"})


@dataclass(frozen=True)
class Derivation:
    formula: str
    #: Field names and number literals, in order.
    operands: tuple
    separator: str = ""

    @property
    def inputs(self) -> tuple[str, ...]:
        return tuple(operand for operand in self.operands if isinstance(operand, str))

    def describe(self) -> str:
        shown = ", ".join(str(operand) for operand in self.operands)
        if self.formula == "concat" and self.separator:
            return f"concat({shown}; separator {self.separator!r})"
        return f"{self.formula}({shown})"


def derivation_of(field: Mapping) -> "Derivation | None":
    """The parsed formula of a field, or None for a stored field.
    Unvalidated: load calls validate_derived_fields first."""
    declared = field.get("derived")
    if declared is None:
        return None
    formula = next(key for key in declared if key in FORMULAS)
    operands = declared[formula]
    if isinstance(operands, str):
        operands = [operands]
    return Derivation(formula, tuple(operands), str(declared.get("separator", "")))


def _type_of(fields: Mapping, name: str) -> str:
    return split_declared_type(fields[name].get("data_type") or DEFAULT_FIELD_DATA_TYPE)[0]


def result_type(derivation: Derivation, fields: Mapping) -> str:
    """The data type a formula yields, from its inputs' declared types."""
    formula = derivation.formula
    if formula == "concat":
        return "string"
    if formula in ("days_between", "years_since"):
        return "integer"
    if formula == "coalesce":
        return _type_of(fields, derivation.inputs[0])
    kinds = {_type_of(fields, operand) for operand in derivation.inputs}
    kinds |= {"decimal" if isinstance(operand, Decimal) else
              "number" if isinstance(operand, float) else "integer"
              for operand in derivation.operands if not isinstance(operand, str)}
    if "decimal" in kinds:
        return "decimal"
    if "number" in kinds or formula == "divide":
        return "number"
    return "integer"


def validate_derived_fields(object_types: Mapping) -> None:
    """Refuses, at load, a derived field that could never be computed."""
    for type_name, type_def in object_types.items():
        fields = type_def.get("fields") or {}
        for field_name, field in fields.items():
            if "derived" not in field:
                continue
            where = f"{type_name}.{field_name}"
            declared = field["derived"]
            if not hasattr(declared, "items"):
                raise ValueError(f"{where}: `derived` must name one formula, such as "
                                 f"{{multiply: [quantity, unit_price]}}.")
            named = [key for key in declared if key in FORMULAS]
            if len(named) != 1:
                raise ValueError(f"{where}: `derived` must name exactly one formula of "
                                 f"{list(FORMULAS)}; it names {named or 'none'}.")
            formula = named[0]
            extra = sorted(set(declared) - {formula} - ({"separator"} if formula == "concat" else set()))
            if extra:
                raise ValueError(f"{where}: unknown key(s) {extra} in `derived`.")
            beside = sorted(set(field) - ALLOWED_BESIDE)
            if beside:
                raise ValueError(f"{where} is derived, so it has no stored value; remove "
                                 f"{beside}.")
            if field.get("type", "data") != "data":
                raise ValueError(f"{where}: a derived field is a value, not a {field['type']}.")
            derivation = derivation_of(field)
            assert derivation is not None
            _check_operands(where, derivation, fields)
            declared_type = field.get("data_type")
            yields = result_type(derivation, fields)
            if declared_type is not None and declared_type != yields:
                raise ValueError(f"{where}: {derivation.describe()} yields {yields}, but the "
                                 f"field declares data_type {declared_type!r}. Remove data_type "
                                 f"or make them agree.")


def _check_operands(where: str, derivation: Derivation, fields: Mapping) -> None:
    formula, operands = derivation.formula, derivation.operands
    if not isinstance(operands, tuple) or not operands:
        raise ValueError(f"{where}: {formula} needs its inputs as a list.")
    expected = {"years_since": 1, "days_between": 2, **dict.fromkeys(ARITHMETIC, 2)}.get(formula)
    if expected is not None and len(operands) != expected:
        raise ValueError(f"{where}: {formula} takes {expected} input(s), got {len(operands)}.")
    if formula in ("concat", "coalesce") and len(operands) < 2:
        raise ValueError(f"{where}: {formula} needs at least two fields.")
    for operand in operands:
        if isinstance(operand, bool) or not isinstance(operand, (str, int, float, Decimal)):
            raise ValueError(f"{where}: {operand!r} is neither a field name nor a number.")
        if not isinstance(operand, str):
            if formula not in ARITHMETIC:
                raise ValueError(f"{where}: {formula} takes field names only, not {operand!r}.")
            continue
        if operand not in fields:
            raise ValueError(f"{where}: {formula} names {operand!r}, which this type does not have.")
        source = fields[operand]
        if source.get("type") == "link":
            raise ValueError(f"{where}: {operand!r} is a link; a formula works on values.")
        if "derived" in source:
            raise ValueError(f"{where}: {operand!r} is itself derived; derive from stored "
                             f"fields directly.")
        kind = _type_of(fields, operand)
        if formula in ARITHMETIC and kind not in _NUMERIC:
            raise ValueError(f"{where}: {formula} needs numbers, and {operand!r} is {kind}.")
        if formula in ("days_between", "years_since") and kind not in _DATES:
            raise ValueError(f"{where}: {formula} needs dates, and {operand!r} is {kind}.")
    if formula in ARITHMETIC and not derivation.inputs:
        raise ValueError(f"{where}: {formula} of two numbers is a constant, not a field.")
    if formula == "coalesce":
        kinds = {_type_of(fields, operand) for operand in operands}
        if len(kinds) != 1:
            raise ValueError(f"{where}: coalesce over different types {sorted(kinds)}; "
                             f"which type is the result?")


def compute(derivation: Derivation, values: Mapping, today: "date | None" = None):
    """The derived value, from `values` -- {field name: coerced value}.
    A field the caller may not read must not be in `values` at all; the
    mediator refuses the whole derived value before getting here."""
    formula = derivation.formula
    if formula == "concat":
        parts = [str(values.get(name)) for name in derivation.inputs
                 if values.get(name) not in (None, "")]
        return derivation.separator.join(parts) if parts else None
    if formula == "coalesce":
        return next((values.get(name) for name in derivation.inputs
                     if values.get(name) is not None), None)
    if formula == "years_since":
        born = _as_date(values.get(derivation.operands[0]))
        if born is None:
            return None
        today = today or datetime.now(UTC).date()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    if formula == "days_between":
        start, end = (_as_date(values.get(name)) for name in derivation.operands)
        return None if start is None or end is None else (end - start).days
    left, right = (values.get(operand) if isinstance(operand, str) else operand
                   for operand in derivation.operands)
    if left is None or right is None:
        return None
    # EXACT ARITHMETIC, THEN THE RESULT'S TYPE. Binary floats made
    # 49.99 x 1.1 into 54.989000000000004 -- seen on the Browse screen,
    # not guessed. Each operand goes through its own text, so 49.99 is
    # the 49.99 a person typed, and only the answer becomes a float.
    try:
        exact_left, exact_right = Decimal(str(left)), Decimal(str(right))
    except InvalidOperation:
        return None
    if formula == "divide" and exact_right == 0:
        return None
    result = {"add": exact_left + exact_right, "subtract": exact_left - exact_right,
              "multiply": exact_left * exact_right}.get(formula)
    if result is None:
        result = exact_left / exact_right
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        return result
    if isinstance(left, float) or isinstance(right, float) or formula == "divide":
        return float(result)
    return int(result)


def finished(value, data_type: str):
    """A computed value as its declared type, the same on read and in
    gold. A decimal is rounded to the scale gold stores (half to even,
    the banker's rule Python's decimal uses by default): a product of
    two 9-place decimals has 18 places, and Arrow refuses to drop them
    silently -- rightly."""
    if value is None:
        return None
    if data_type == "decimal":
        # ROUNDED BEFORE coerce(), which refuses more places than gold
        # holds -- correctly, for a value somebody TYPED. A computed one
        # is ours to round, and saying so is this comment.
        value = Decimal(str(value)).quantize(Decimal(1).scaleb(-DECIMAL_SCALE),
                                             rounding=ROUND_HALF_EVEN)
    return coerce(value, data_type)


def _as_date(value) -> "date | None":
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def derived_fields(type_def: Mapping) -> dict[str, Derivation]:
    """{field name: Derivation} for every derived field of a type."""
    return {name: derivation
            for name, field in (type_def.get("fields") or {}).items()
            if (derivation := derivation_of(field)) is not None}


def fill_result_types(object_types: Mapping) -> None:
    """Writes each derived field's `type: data` and data_type into the RAW schema, before
    it is frozen, so gold, the mediator's coercion, data contracts and
    the schema screen all read one declared type -- the one the formula
    yields -- without each knowing about formulas."""
    for type_def in object_types.values():
        fields = type_def.get("fields") or {}
        for field in fields.values():
            derivation = derivation_of(field)
            if derivation is None:
                continue
            # A VALUE, as every reader of a field asks first -- `type`
            # is optional to write on a derived field and never absent
            # once loaded.
            field.setdefault("type", "data")
            if field.get("data_type") is None:
                field["data_type"] = result_type(derivation, fields)


def refuse_rules_over_derived(object_types: Mapping) -> None:
    """A cross-field rule (R29) is checked on SOURCE rows in silver,
    and a derived field is in no source row."""
    for type_name, type_def in object_types.items():
        fields = type_def.get("fields") or {}
        for rule_name, rule in (type_def.get("rules") or {}).items():
            for key in ("field", "other"):
                name = (rule or {}).get(key)
                if name in fields and is_computed(fields[name]):
                    raise ValueError(
                        f"{type_name} rule {rule_name!r} compares {name!r}, which is computed, "
                        f"not stored; a rule is checked on source rows, so compare its inputs "
                        f"instead.")


def gate_derived_grants(roles: Mapping, schema: Mapping) -> Mapping:
    """The roles, with every `read:` grant on a derived field WITHDRAWN
    from a role that may not read all of its inputs -- and replaced by
    `discover:`, so the field still shows as present-but-hidden.

    AT LOAD, ONCE, rather than at every place a read is decided: grants
    are exact strings (core/intermediate_layer/auth.py), every read the
    mediators decide goes through the roles this returns, and so one
    rewrite covers field reads, bulk reads, filters, the schema screen
    and the agent alike. Checking at each site instead would be eight
    places to keep in step, and the one forgotten is the leak.

    Returns `roles` itself when nothing changes, so a deployment with no
    derived fields keeps the exact object it had."""
    from core.ontology.enriched_fields import enriched_fields

    # AN ENRICHED FIELD (R41) TOO: an inferred mood summarises the
    # ticket's text exactly as a total summarises a price, and would
    # hand out what the text says to someone refused the text.
    derived = [(type_name, field_name, derivation.inputs)
               for type_name, type_def in schema.items()
               for field_name, derivation in derived_fields(type_def).items()]
    derived += [(type_name, field_name, enrichment.inputs)
                for type_name, type_def in schema.items()
                for field_name, enrichment in enriched_fields(type_def).items()]
    # A PREDICTED FIELD (R48) summarises its inputs AND the answer it
    # learned: someone refused `churned` must not read a chance of it.
    from core.ontology.predicted_fields import predicted_fields

    derived += [(type_name, field_name, (*prediction.inputs, prediction.target))
                for type_name, type_def in schema.items()
                for field_name, prediction in predicted_fields(type_def).items()]
    if not derived:
        return roles
    gated = {}
    changed = False
    for role_name, role in roles.items():
        allowed = set(role.get("allowed_actions") or ())
        for type_name, field_name, inputs in derived:
            grant = f"read:{type_name}.{field_name}"
            if grant in allowed and not all(f"read:{type_name}.{name}" in allowed for name in inputs):
                allowed.discard(grant)
                allowed.add(f"discover:{type_name}.{field_name}")
                changed = True
        gated[role_name] = {**role, "allowed_actions": frozenset(allowed)}
    return gated if changed else roles
