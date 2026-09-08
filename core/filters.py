"""
filters.py  (the filter vocabulary -- what a search may ask for)

Elysium's filter was equality only: one value per field, so
`region = 'us-west'` and nothing else. That is enough for a lookup and
not enough for exploration. Selecting two values on a chart means "in
these two", a date range means "between these", and neither could be
expressed at all.

THE VOCABULARY IS DELIBERATELY CLOSED. Seven operators, each one added
because a real interaction needs it, rather than a general expression
language:

    equals         a single value
    in / not_in    a set -- selecting values on a chart, and the
                   "exclude these" that makes selection more than a
                   dropdown
    range          numeric min/max, either side optional
    date_range     absolute start/end
    relative_date  "the last N days", resolved server-side in UTC
    contains       substring, for text

A closed set is checkable. An open one -- arbitrary nesting, OR across
fields, user-supplied SQL fragments -- would have to be parsed and
sanitised, and the thing being parsed decides which rows a caller
sees. Every operator here maps to one SQL construct with bound
parameters, so there is nothing to sanitise.

FIELD NAMES ARE NOT VALIDATED HERE. The mediator does that, against
the caller's OWN visible schema, before a filter reaches an adapter --
a field the caller cannot read must be indistinguishable from one that
does not exist. This module validates the SHAPE of an expression and
the TYPES of its values; it has no idea who is asking.

RELATIVE DATES RESOLVE IN UTC, on the server, at query time. A saved
search must mean the same thing to everyone who opens it, and
browser-local would make "the last 7 days" differ by timezone -- so a
search saved in Berlin and opened in Denver would silently return a
different set.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

# Operators that take a LIST of values rather than one.
SET_OPERATORS = ("in", "not_in")

# Which declared data_types each operator accepts. A field with no
# declared data_type accepts anything -- declaring the type is how an
# author opts into this check, the same bargain the mutation-value
# check makes.
OPERATOR_TYPES: dict[str, tuple[str, ...] | None] = {
    "equals": None,  # any type
    "in": None,
    "not_in": None,
    "range": ("integer", "number"),
    "date_range": ("string",),  # ISO-8601 text; see _validate_date_range
    "relative_date": ("string",),
    "contains": ("string",),
}


@dataclass(frozen=True)
class FieldFilter:
    """One condition on one field.

    Frozen because a filter is a request, not a workspace: something
    that mutated a filter after validation would be changing a query
    that had already been checked.
    """

    field: str
    operator: str
    value: Any


class UnsupportedFilter(Exception):
    """Raised by an adapter that cannot push a given operator down.

    Deliberately NOT a FilterError: a FilterError means the filter is
    wrong and the caller must fix it, while this means the filter is
    fine and this storage cannot express it. The mediator catches this
    one and applies the condition in Python; letting it reach a caller
    as a 400 would report a backend limitation as user error.
    """


class FilterError(ValueError):
    """A filter that cannot be honoured as written.

    A ValueError subclass so existing callers that catch ValueError --
    the API's 400 path among them -- keep working unchanged.
    """


def as_equality_conditions(criteria: dict | None) -> list[FieldFilter]:
    """A {field: value} dict as equality conditions.

    For callers whose OWN public surface still takes a dict --
    OntologyAccess.search(), count_objects(), search_around(), the
    agent's emitted filter, the HTTP body. search_object() speaks
    conditions now; those APIs adopt the vocabulary in their own
    changes, and this is the boundary until they do.

    NOT the dict shape returning by the back door. parse_filters()
    rejects a dict deliberately, because two accepted wire shapes is
    two things to keep correct. This is an explicit conversion a caller
    asks for, named so it is visible at every call site that still
    needs it.
    """
    return [
        FieldFilter(field=field, operator="equals", value=value)
        for field, value in (criteria or {}).items()
    ]


def parse_filters(raw: Any) -> list[FieldFilter]:
    """Turns the wire form -- a list of conditions -- into validated
    FieldFilters.

    ONE shape, not two. An earlier version also accepted a plain
    {field: value} dict as equality-on-each-key, to spare migrating
    existing callers. Nothing had called it yet, so that was a bridge
    built for traffic that did not exist -- and two accepted shapes is
    two things to keep correct, in the module that decides which rows a
    caller sees.

    Callers migrate to conditions when the adapter contract changes;
    until then they pass their dicts to the old path, untouched.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise FilterError(
            "A filter must be a list of conditions, each with a field and an "
            "operator."
        )

    parsed = []
    for index, condition in enumerate(raw):
        if not isinstance(condition, dict):
            raise FilterError(f"Condition {index} must be an object.")
        missing = {"field", "operator"} - set(condition)
        if missing:
            raise FilterError(
                f"Condition {index} is missing {sorted(missing)}."
            )
        operator = condition["operator"]
        if operator not in OPERATOR_TYPES:
            raise FilterError(
                f"Unknown filter operator {operator!r} -- known operators: "
                f"{sorted(OPERATOR_TYPES)}."
            )
        parsed.append(
            FieldFilter(
                field=condition["field"],
                operator=operator,
                value=condition.get("value"),
            )
        )
    return parsed


def validate_filter(condition: FieldFilter, declared_type: str | None) -> None:
    """Checks one condition's shape and value types.

    `declared_type` is the field's own data_type, or None when the
    ontology declares none. None means "no expectation to violate", so
    only shape is checked -- inventing one would reject valid schemas.
    """
    allowed = OPERATOR_TYPES[condition.operator]
    if allowed is not None and declared_type is not None and declared_type not in allowed:
        raise FilterError(
            f"Operator {condition.operator!r} cannot be used on field "
            f"{condition.field!r}, which declares data_type {declared_type!r} -- "
            f"it applies to {list(allowed)}."
        )

    if condition.operator in SET_OPERATORS:
        _validate_set(condition)
    elif condition.operator == "range":
        _validate_range(condition)
    elif condition.operator == "date_range":
        _validate_date_range(condition)
    elif condition.operator == "relative_date":
        _validate_relative_date(condition)
    elif condition.operator == "contains":
        if not isinstance(condition.value, str) or condition.value == "":
            raise FilterError(
                f"{condition.field!r}: contains needs a non-empty string."
            )


def _validate_set(condition: FieldFilter) -> None:
    if not isinstance(condition.value, list) or not condition.value:
        raise FilterError(
            f"{condition.field!r}: {condition.operator} needs a non-empty list "
            f"of values."
        )
    # An empty set would mean "match nothing" for `in` and "match
    # everything" for `not_in` -- opposite outcomes from the same
    # mistake, which is exactly the kind of silent difference worth
    # rejecting rather than guessing at.


def _validate_range(condition: FieldFilter) -> None:
    value = condition.value
    if not isinstance(value, dict) or not ({"min", "max"} & set(value)):
        raise FilterError(
            f"{condition.field!r}: range needs an object with min, max, or both."
        )
    for bound in ("min", "max"):
        if value.get(bound) is not None and not isinstance(value[bound], (int, float)):
            raise FilterError(
                f"{condition.field!r}: range {bound} must be a number, got "
                f"{value[bound]!r}."
            )
    low, high = value.get("min"), value.get("max")
    if low is not None and high is not None and low > high:
        raise FilterError(
            f"{condition.field!r}: range min {low} is greater than max {high} -- "
            f"this matches nothing, which is more likely a mistake than an intent."
        )


def _validate_date_range(condition: FieldFilter) -> None:
    value = condition.value
    if not isinstance(value, dict) or not ({"start", "end"} & set(value)):
        raise FilterError(
            f"{condition.field!r}: date_range needs an object with start, end, "
            f"or both."
        )
    for bound in ("start", "end"):
        if value.get(bound) is None:
            continue
        if not isinstance(value[bound], str):
            raise FilterError(
                f"{condition.field!r}: date_range {bound} must be an ISO-8601 "
                f"string, got {value[bound]!r}."
            )
        try:
            datetime.fromisoformat(value[bound])
        except ValueError as e:
            raise FilterError(
                f"{condition.field!r}: date_range {bound} {value[bound]!r} is not "
                f"a valid ISO-8601 date."
            ) from e


def _validate_relative_date(condition: FieldFilter) -> None:
    value = condition.value
    if not isinstance(value, dict) or not ({"since_days_ago", "until_days_ago"} & set(value)):
        raise FilterError(
            f"{condition.field!r}: relative_date needs since_days_ago, "
            f"until_days_ago, or both."
        )
    for bound in ("since_days_ago", "until_days_ago"):
        if value.get(bound) is None:
            continue
        if not isinstance(value[bound], int) or isinstance(value[bound], bool):
            raise FilterError(
                f"{condition.field!r}: relative_date {bound} must be a whole "
                f"number of days, got {value[bound]!r}."
            )
        if value[bound] < 0:
            raise FilterError(
                f"{condition.field!r}: relative_date {bound} cannot be negative -- "
                f"days_ago counts backwards from now."
            )
    since, until = value.get("since_days_ago"), value.get("until_days_ago")
    if since is not None and until is not None and until > since:
        raise FilterError(
            f"{condition.field!r}: until_days_ago {until} is further back than "
            f"since_days_ago {since} -- this matches nothing."
        )


def resolve_relative_date(value: dict, now: datetime | None = None) -> dict:
    """Turns days-ago into an absolute UTC range.

    Resolved on the SERVER, in UTC, at query time. A saved search must
    mean the same thing to everyone who opens it: browser-local would
    make "the last 7 days" differ by timezone, so a search saved in
    Berlin and opened in Denver would quietly return a different set.

    `now` is injectable so a test can pin it -- a test that computed
    its own expectation from the clock would be asserting the same
    arithmetic twice.
    """
    reference = now or datetime.now(UTC)
    resolved: dict[str, str | None] = {"start": None, "end": None}
    if value.get("since_days_ago") is not None:
        resolved["start"] = (reference - timedelta(days=value["since_days_ago"])).isoformat()
    if value.get("until_days_ago") is not None:
        resolved["end"] = (reference - timedelta(days=value["until_days_ago"])).isoformat()
    return resolved


def row_matches(row: dict, condition: FieldFilter) -> bool:
    """Whether one row satisfies one condition, in Python.

    The SAME semantics the adapters express in SQL, for the fallback
    path when a storage cannot push an operator down. Kept beside the
    vocabulary rather than in the mediator so the two definitions of
    each operator sit in one file and can be read against each other --
    two implementations of "what does `in` mean" drifting apart would
    make results depend on which storage answered.
    """
    value = row.get(condition.field)
    operand = condition.value

    if condition.operator == "equals":
        return value == operand
    if condition.operator == "in":
        return value in operand
    if condition.operator == "not_in":
        return value not in operand
    if condition.operator == "contains":
        return isinstance(value, str) and operand in value
    if condition.operator in ("range", "date_range"):
        low = operand.get("min") if condition.operator == "range" else operand.get("start")
        high = operand.get("max") if condition.operator == "range" else operand.get("end")
        if value is None:
            return False
        if low is not None and value < low:
            return False
        return not (high is not None and value > high)

    raise FilterError(f"Cannot evaluate {condition.operator!r} in Python.")
