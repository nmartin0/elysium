"""
object_sets.py  (one composable way to describe a set of objects)

Today a set of objects is described five different ways: search criteria,
search-around, combine and compare of frozen sets, the matching-ids
selection, and the conditions an aggregate takes. Precedent has ONE
description, a JSON union that composes, and every operation (load, count,
aggregate) takes it. This module is that description, for the standard
read surface under /api/v2. It adds a way in; the existing routes are
untouched.

    {"type": "base", "objectType": "Transaction"}
    {"type": "filter", "objectSet": <set>, "where": <filter>}
    {"type": "union" | "intersect" | "subtract", "objectSets": [<set>, ...]}
    {"type": "searchAround", "objectSet": <set>, "link": "customer_id"}
    {"type": "static", "objectType": "Customer", "primaryKeys": ["cust_001"]}

THE FILTER, a union discriminated by `type`:

    {"type": "and" | "or", "value": [<filter>, ...]}     {"type": "not", "value": <filter>}
    {"type": "eq" | "lt" | "lte" | "gt" | "gte", "field": "amount", "value": 100}
    {"type": "in", "field": "status", "value": ["open", "late"]}
    {"type": "isNull", "field": "email", "value": true}
    {"type": "contains" | "startsWith", "field": "name", "value": "ada"}

LEFT OUT OF THIS SLICE: `reference` (a stored, named set -- there is no
store yet) and `similarTo` (search by meaning is gated by its own grant
and needs its own design). Both are refused as unknown kinds, naming the
ones that exist.

THREE STAGES, kept apart on purpose:

  parse     the wire form into a typed tree. Knows the grammar and the caps
            and NOTHING about any deployment or any caller.
  prepare   the tree against ONE CALLER'S visible schema: resolves every
            type, field and link, checks every operator against the field's
            declared type, coerces every value. Reads no data.
  run       evaluates a prepared set. Every id it returns came out of the
            mediator's own search_object() or search_around_from(), so it
            passed check_access() -- RBAC and MAC -- exactly as a read does
            today; the set algebra only ever combines ids that already
            passed. Values for filtering and sorting come from
            DataMediator.field_values_for_ids(), which checks every id
            again before it reads a column.

THERE IS NO SECOND READ PATH. This module opens no adapter, names no
table and builds no query of its own. The one optimisation, handing a
filter's simple equality tests to search_object() so a large table is not
cut off at the scan ceiling before the filter sees it, narrows what the
mediator searches and is then applied AGAIN in Python, so a mismatch
between the two could only ever make a result smaller, never reveal a row.

UNIFORM DENIAL. A field the caller may not read, a field that does not
exist, and a field that cannot be filtered because it is a reverse link are
different facts; the first two are reported with the SAME words
("Unknown field"), so a refusal teaches nothing about what is hidden. A
type that is unknown and a type the caller may not read both raise
ObjectSetNotFound, which the API answers as a 404 and never as a 403.

TWO-VALUED LOGIC: a row whose value is null matches NO comparison (eq, in,
lt, ..., contains, startsWith), and `not` inverts the result, so
not(eq(status, "open")) matches a row whose status is null. Use isNull to
ask about nulls on purpose.
"""

import decimal
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core.filters import FieldFilter
from core.ontology import mediator as mediator_module
from core.ontology.field_types import coerce
from core.ontology.mediator import SearchOutcome
from core.ontology.schema import (
    get_field_storage_name,
    get_link_target,
    id_sort_key,
    is_link_field,
    is_searchable_field,
    sort_key,
)

# --- the caps. Every one is a refusal with a message, never a silent cut. ---

#: How deep object sets may nest (a filter of a union of ... ).
MAX_SET_DEPTH = 8
#: How many object-set nodes one request may hold in total.
MAX_SET_NODES = 64
#: How deep a filter may nest and how many filter nodes it may hold.
MAX_FILTER_DEPTH = 6
MAX_FILTER_NODES = 100
#: Values in one `in`, and keys in one `static` set.
MAX_IN_VALUES = 1000
#: Values across EVERY `in` of one request. MAX_IN_VALUES alone bounds one
#: node; 64 nodes of 1000 values each, matched against every row, is the
#: shape this closes.
MAX_TOTAL_IN_VALUES = 2000
MAX_STATIC_KEYS = 10_000
#: What the leaves of one request may cost in total, charged BEFORE it runs
#: from the shape of the set alone (see _cost): a search leaf is worth the
#: scan ceiling, a static leaf its keys. A request over it is refused, never
#: silently cut. Nothing about the budget may depend on the data.
MAX_SCANNED_ROWS = 50_000
#: The longest text a filter value may be.
MAX_VALUE_LENGTH = 1000
#: Fields one request may sort by, select, or measure.
MAX_ORDER_BY = 3
MAX_SELECT_FIELDS = 100
MAX_METRICS = 8

FILTER_TYPES = ("and", "or", "not", "eq", "lt", "lte", "gt", "gte", "in", "isNull", "contains", "startsWith")
SET_TYPES = ("base", "filter", "union", "intersect", "subtract", "searchAround", "static")
METRIC_TYPES = ("count", "sum", "min", "max", "avg")

_COMPARISONS = ("eq", "lt", "lte", "gt", "gte")
_TEXT = ("contains", "startsWith")
#: The declared data types that have an order, and so take lt..gte. An
#: undeclared type is text. Booleans and links have identity, not order.
_ORDERED_TYPES = frozenset({"integer", "number", "decimal", "date", "timestamp", "timestamptz", "string"})
_NUMERIC_TYPES = frozenset({"integer", "number", "decimal"})
_METRIC_NAME = re.compile(r"[a-z_][a-z0-9_]*")


class ObjectSetError(ValueError):
    """The request is wrong, and the message says how. Safe to show: it
    never names anything the caller could not already discover."""

    def __init__(self, message: str, parameters: "Mapping[str, Any] | None" = None):
        super().__init__(message)
        self.parameters = dict(parameters or {})


class ObjectSetNotFound(Exception):
    """An object type that is unknown OR that the caller may not read --
    one outcome, so the API can answer both with the same 404."""


#: THE ONE SENTENCE for fields no single read can combine.
MULTI_STORAGE_SENTENCE = "These fields cannot be combined in one request."


#: THE ONE SENTENCE for a set the scan ceiling cut short where the cut may
#: hide visible rows. It carries no count.
TOO_LARGE_SENTENCE = "This set is too large to evaluate; narrow it."


def _unknown_field(object_type: str, name: Any) -> ObjectSetError:
    # THE ONE SENTENCE for a field that does not exist and for one the
    # caller may not read. Two sentences, however similar, would be a
    # question the caller could ask.
    return ObjectSetError(f"Unknown field {name!r} on {object_type!r}.",
                          {"objectType": object_type, "field": name})


# ---------------------------------------------------------------- the tree

@dataclass(frozen=True)
class Base:
    object_type: str


@dataclass(frozen=True)
class Static:
    object_type: str
    primary_keys: tuple[str, ...]


@dataclass(frozen=True)
class Filter:
    object_set: "ObjectSet"
    where: "FilterNode"


@dataclass(frozen=True)
class Combine:
    kind: str  # union | intersect | subtract
    object_sets: tuple["ObjectSet", ...]


@dataclass(frozen=True)
class SearchAround:
    object_set: "ObjectSet"
    link: str


ObjectSet = Base | Static | Filter | Combine | SearchAround


@dataclass(frozen=True)
class Compare:
    operator: str  # eq | lt | lte | gt | gte
    field: str
    value: Any


@dataclass(frozen=True)
class In:
    field: str
    values: tuple[Any, ...]


@dataclass(frozen=True)
class IsNull:
    field: str
    is_null: bool


@dataclass(frozen=True)
class Text:
    operator: str  # contains | startsWith
    field: str
    value: str


@dataclass(frozen=True)
class Junction:
    operator: str  # and | or
    children: tuple["FilterNode", ...]


@dataclass(frozen=True)
class Not:
    child: "FilterNode"


FilterNode = Compare | In | IsNull | Text | Junction | Not


@dataclass(frozen=True)
class OrderTerm:
    field: str
    descending: bool = False


@dataclass(frozen=True)
class Metric:
    name: str
    aggregate: str
    field: str | None = None


# ---------------------------------------------------------------- parsing

class _Budget:
    """Counts nodes so a request cannot be made huge by width alone."""

    def __init__(self, limit: int, what: str):
        self.left = limit
        self.limit = limit
        self.what = what

    def spend(self, count: int = 1) -> None:
        self.left -= count
        if self.left < 0:
            raise ObjectSetError(f"At most {self.limit} {self.what} in one request.",
                                 {"limit": self.limit})


class _Caps:
    """The budgets of ONE request, shared by every node in it: a cap that
    each filter node got afresh would be a cap per node, not per request."""

    def __init__(self) -> None:
        self.sets = _Budget(MAX_SET_NODES, "object set nodes")
        self.filters = _Budget(MAX_FILTER_NODES, "filter nodes")
        self.in_values = _Budget(MAX_TOTAL_IN_VALUES, "`in` values")


def _object(raw: Any, where: str) -> dict:
    if not isinstance(raw, dict):
        raise ObjectSetError(f"{where} must be an object with a `type`.")
    return raw


def _only_keys(raw: dict, allowed: set[str], where: str) -> None:
    extra = sorted(set(raw) - allowed - {"type"})
    if extra:
        raise ObjectSetError(f"{where} does not take {extra}; it takes {sorted(allowed)}.")


def _name(raw: dict, key: str, where: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ObjectSetError(f"{where} needs `{key}`, a non-empty string.")
    return value


def _scalar(value: Any, where: str) -> Any:
    if value is None or isinstance(value, (dict, list)):
        raise ObjectSetError(f"{where}: the value must be a string, number or boolean "
                             f"(use isNull to ask about nulls).")
    if isinstance(value, str) and len(value) > MAX_VALUE_LENGTH:
        raise ObjectSetError(f"{where}: a value may be at most {MAX_VALUE_LENGTH} characters.")
    return value


def parse_object_set(raw: Any) -> ObjectSet:
    """The wire form as a typed tree, or ObjectSetError."""
    return _parse_set(raw, 1, _Caps())


def _parse_set(raw: Any, depth: int, caps: _Caps) -> ObjectSet:
    if depth > MAX_SET_DEPTH:
        raise ObjectSetError(f"Object sets may nest at most {MAX_SET_DEPTH} deep.",
                             {"limit": MAX_SET_DEPTH})
    caps.sets.spend()
    raw = _object(raw, "An object set")
    kind = raw.get("type")
    if kind not in SET_TYPES:
        raise ObjectSetError(f"Unknown object set type {kind!r}; the types are {list(SET_TYPES)}.")
    where = f"A {kind} object set"
    if kind == "base":
        _only_keys(raw, {"objectType"}, where)
        return Base(_name(raw, "objectType", where))
    if kind == "static":
        _only_keys(raw, {"objectType", "primaryKeys"}, where)
        keys = raw.get("primaryKeys")
        if not isinstance(keys, list):
            raise ObjectSetError(f"{where} needs `primaryKeys`, a list.")
        if len(keys) > MAX_STATIC_KEYS:
            raise ObjectSetError(f"A static set holds at most {MAX_STATIC_KEYS} keys.",
                                 {"limit": MAX_STATIC_KEYS})
        for key in keys:
            if isinstance(key, bool) or not isinstance(key, (str, int)):
                raise ObjectSetError(f"{where}: each primary key must be a string or an integer.")
        return Static(_name(raw, "objectType", where), tuple(dict.fromkeys(str(key) for key in keys)))
    if kind == "filter":
        _only_keys(raw, {"objectSet", "where"}, where)
        if "objectSet" not in raw or "where" not in raw:
            raise ObjectSetError(f"{where} needs `objectSet` and `where`.")
        child = _parse_set(raw["objectSet"], depth + 1, caps)
        return Filter(child, parse_filter(raw["where"], caps))
    if kind == "searchAround":
        _only_keys(raw, {"objectSet", "link"}, where)
        if "objectSet" not in raw:
            raise ObjectSetError(f"{where} needs `objectSet`.")
        child = _parse_set(raw["objectSet"], depth + 1, caps)
        return SearchAround(child, _name(raw, "link", where))
    _only_keys(raw, {"objectSets"}, where)
    members = raw.get("objectSets")
    if not isinstance(members, list) or len(members) < 2:
        raise ObjectSetError(f"{where} needs `objectSets`, a list of at least two sets.")
    return Combine(kind, tuple(_parse_set(member, depth + 1, caps) for member in members))


def parse_filter(raw: Any, caps: "_Caps | None" = None) -> FilterNode:
    """The wire form of a filter as a typed tree, or ObjectSetError.
    Inside a set the request's own `caps` are passed, so the filter and
    `in` budgets are shared by every filter node of the request."""
    return _parse_filter(raw, 1, caps or _Caps())


def _parse_filter(raw: Any, depth: int, caps: _Caps) -> FilterNode:
    if depth > MAX_FILTER_DEPTH:
        raise ObjectSetError(f"Filters may nest at most {MAX_FILTER_DEPTH} deep.",
                             {"limit": MAX_FILTER_DEPTH})
    caps.filters.spend()
    raw = _object(raw, "A filter")
    kind = raw.get("type")
    if kind not in FILTER_TYPES:
        raise ObjectSetError(f"Unknown filter type {kind!r}; the types are {list(FILTER_TYPES)}.")
    where = f"A {kind} filter"
    if kind in ("and", "or"):
        _only_keys(raw, {"value"}, where)
        members = raw.get("value")
        if not isinstance(members, list) or not members:
            raise ObjectSetError(f"{where} needs `value`, a non-empty list of filters.")
        return Junction(kind, tuple(_parse_filter(member, depth + 1, caps) for member in members))
    if kind == "not":
        _only_keys(raw, {"value"}, where)
        if "value" not in raw:
            raise ObjectSetError(f"{where} needs `value`, a filter.")
        return Not(_parse_filter(raw["value"], depth + 1, caps))
    _only_keys(raw, {"field", "value"}, where)
    field_name = _name(raw, "field", where)
    if "value" not in raw:
        raise ObjectSetError(f"{where} needs `value`.")
    value = raw["value"]
    if kind == "in":
        if not isinstance(value, list) or not value:
            raise ObjectSetError(f"{where} needs `value`, a non-empty list.")
        if len(value) > MAX_IN_VALUES:
            raise ObjectSetError(f"An `in` holds at most {MAX_IN_VALUES} values.",
                                 {"limit": MAX_IN_VALUES})
        caps.in_values.spend(len(value))
        return In(field_name, tuple(_scalar(item, where) for item in value))
    if kind == "isNull":
        if not isinstance(value, bool):
            raise ObjectSetError(f"{where} needs `value`, true or false.")
        return IsNull(field_name, value)
    if kind in _TEXT:
        if not isinstance(value, str) or not value or len(value) > MAX_VALUE_LENGTH:
            raise ObjectSetError(f"{where} needs `value`, a non-empty string "
                                 f"of at most {MAX_VALUE_LENGTH} characters.")
        return Text(kind, field_name, value)
    return Compare(kind, field_name, _scalar(value, where))


def parse_order_by(raw: Any) -> tuple[OrderTerm, ...]:
    """`[{"field": "amount", "direction": "desc"}, ...]`, or ObjectSetError."""
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > MAX_ORDER_BY:
        raise ObjectSetError(f"orderBy must be a list of at most {MAX_ORDER_BY} terms.",
                             {"limit": MAX_ORDER_BY})
    terms = []
    for item in raw:
        item = _object(item, "An orderBy term")
        direction = item.get("direction", "asc")
        if direction not in ("asc", "desc"):
            raise ObjectSetError("An orderBy direction is `asc` or `desc`.")
        terms.append(OrderTerm(_name(item, "field", "An orderBy term"), direction == "desc"))
    return tuple(terms)


def parse_order_by_text(text: str | None) -> tuple[OrderTerm, ...]:
    """The query-string form, `amount:desc,name`."""
    if not text:
        return ()
    terms = []
    for part in text.split(","):
        name, _, direction = part.strip().partition(":")
        terms.append({"field": name, "direction": (direction or "asc").lower()})
    return parse_order_by(terms)


def parse_select(raw: Any) -> tuple[str, ...]:
    """`["name", "email"]`, or ObjectSetError."""
    if raw is None:
        return ()
    if (not isinstance(raw, list) or len(raw) > MAX_SELECT_FIELDS
            or not all(isinstance(item, str) and item for item in raw)):
        raise ObjectSetError(f"select must be a list of at most {MAX_SELECT_FIELDS} field names.",
                             {"limit": MAX_SELECT_FIELDS})
    return tuple(dict.fromkeys(raw))


def parse_metrics(raw: Any) -> tuple[Metric, ...]:
    """`[{"type": "sum", "field": "amount", "name": "total"}, ...]`."""
    if not isinstance(raw, list) or not raw or len(raw) > MAX_METRICS:
        raise ObjectSetError(f"metrics must be a list of 1 to {MAX_METRICS} metrics.",
                             {"limit": MAX_METRICS})
    metrics = []
    for item in raw:
        item = _object(item, "A metric")
        kind = item.get("type")
        if kind not in METRIC_TYPES:
            raise ObjectSetError(f"Unknown metric type {kind!r}; the types are {list(METRIC_TYPES)}.")
        field_name = item.get("field")
        if kind == "count":
            if field_name is not None:
                raise ObjectSetError("A count metric counts the set and takes no field.")
        elif not isinstance(field_name, str) or not field_name:
            raise ObjectSetError(f"A {kind} metric needs `field`.")
        name = item.get("name") or (kind if field_name is None else f"{kind}_{field_name}")
        if not isinstance(name, str) or not _METRIC_NAME.fullmatch(name):
            raise ObjectSetError("A metric's name is lower-case letters, digits and underscores, "
                                 "starting with a letter or underscore.")
        metrics.append(Metric(name, kind, field_name))
    if len({metric.name for metric in metrics}) != len(metrics):
        raise ObjectSetError("Two metrics have the same name; each needs its own.")
    return tuple(metrics)


# ------------------------------------------------- the caller's schema view

@dataclass(frozen=True)
class FieldSpec:
    name: str
    data_type: str  # declared, "string" when undeclared
    is_link: bool = False
    #: The type's primary key. The mirror holds keys as text whatever the
    #: source's type was, so a key has identity here, not an arithmetic order.
    is_id: bool = False
    #: The type a link points to, when the caller's schema names it.
    target: str | None = None


class SchemaView:
    """What ONE caller may know and use, taken from the mediator's own
    visible_schema() -- the single source of "what does this user get to
    know exists" -- and nothing else."""

    def __init__(self, mediator: Any, user_record: Any):
        self.visible: dict = mediator.visible_schema(user_record)
        self.declared: dict = mediator.schema

    def has_type(self, object_type: str) -> bool:
        """Readable AND with a readable key: an id is data, and a type
        whose key the caller cannot read has nothing to key a row by."""
        info = self.visible.get(object_type)
        return info is not None and bool(info["readable"]) and info["id_field"] is not None

    def require_type(self, object_type: str) -> dict:
        if not self.has_type(object_type):
            raise ObjectSetNotFound(object_type)
        return self.visible[object_type]

    def id_field(self, object_type: str) -> str:
        return str(self.require_type(object_type)["id_field"])

    def title_field(self, object_type: str) -> str | None:
        return self.require_type(object_type)["title_field"]

    def _info(self, object_type: str, name: Any) -> dict:
        type_info = self.require_type(object_type)
        if name == type_info["id_field"]:
            return {"type": "data", "readable": True, "derived": None, "inferred": None}
        info = type_info["fields"].get(name) if isinstance(name, str) else None
        if info is None or info.get("readable") is not True:
            raise _unknown_field(object_type, name)
        return info

    def _declared_type(self, object_type: str, name: str) -> str | None:
        declared = ((self.declared.get(object_type) or {}).get("fields") or {}).get(name) or {}
        return declared.get("data_type")

    def selectable(self, object_type: str, name: Any) -> str:
        """A field a row may carry: any the caller may read."""
        self._info(object_type, name)
        return str(name)

    def selectable_fields(self, object_type: str) -> list[str]:
        type_info = self.require_type(object_type)
        return [name for name, info in type_info["fields"].items() if info.get("readable") is True]

    def filterable(self, object_type: str, name: Any) -> FieldSpec:
        """A field the set algebra may read a stored column of."""
        info = self._info(object_type, name)
        # THE RAW SCHEMA DECIDES WHAT A LINK IS, not the caller's view of it:
        # visible_schema shows a link to a type the caller is not told about
        # as plain `data`, so a value the caller may not follow would be
        # filterable and sortable -- prefix by prefix -- as if it were text.
        # Such a field is refused in the words used for one that does not exist.
        raw = ((self.declared.get(object_type) or {}).get("fields") or {}).get(name)
        # A target that is not a declared type at all is an opaque reference
        # (nothing to hide, nothing to enforce); only a DECLARED type the
        # caller cannot see makes the value one they may not use.
        if (raw is not None and is_link_field(raw) and get_link_target(raw) in self.declared
                and not self.has_type(get_link_target(raw))):
            raise _unknown_field(object_type, name)
        if not is_searchable_field(info):
            raise ObjectSetError(f"Field {name!r} on {object_type!r} is a reverse link; "
                                 f"it cannot be filtered or sorted on. Use searchAround.",
                                 {"objectType": object_type, "field": name})
        if info.get("derived") is not None or info.get("inferred") is not None:
            raise ObjectSetError(f"Field {name!r} on {object_type!r} is computed; "
                                 f"it cannot be filtered or sorted on.",
                                 {"objectType": object_type, "field": name})
        is_link = is_link_field(info)
        is_id = name == self.visible[object_type]["id_field"]
        declared = None if is_id else self._declared_type(object_type, name)
        return FieldSpec(str(name), "string" if is_link or declared is None else declared, is_link, is_id,
                         get_link_target(info) if is_link else None)

    def one_storage(self, object_type: str, names: "list[str]") -> None:
        """Refuses fields backed by more than one storage, which no single
        read can combine. The sentence names neither the fields nor the
        storages: it is the same for every pair, so it teaches nothing of
        how the type is laid out."""
        declared = self.declared.get(object_type) or {}
        fields = declared.get("fields") or {}
        id_field = declared.get("id_field")
        storages = {None if name == id_field else get_field_storage_name(fields.get(name) or {})
                    for name in names}
        if len(storages) > 1:
            raise ObjectSetError(MULTI_STORAGE_SENTENCE, {"objectType": object_type})

    def link(self, object_type: str, name: str) -> str:
        """The target type of a DECLARED link the caller may read."""
        type_info = self.require_type(object_type)
        info = type_info["fields"].get(name)
        if info is None or info.get("readable") is not True or not is_link_field(info):
            raise ObjectSetError(f"Unknown link {name!r} on {object_type!r}.",
                                 {"objectType": object_type, "link": name})
        target = get_link_target(info)
        if not self.has_type(target):
            raise ObjectSetError(f"Unknown link {name!r} on {object_type!r}.",
                                 {"objectType": object_type, "link": name})
        return target


# -------------------------------------------------------- filter compiling

Predicate = Callable[[Mapping[str, Any]], bool]


def _typed(value: Any, data_type: str) -> Any:
    return coerce(value, data_type)


def _filter_value(value: Any, spec: FieldSpec, object_type: str) -> Any:
    try:
        return _typed(value, spec.data_type)
    except (ValueError, TypeError, decimal.InvalidOperation):
        raise ObjectSetError(
            f"The value {value!r} is not a valid {spec.data_type} for field {spec.name!r} "
            f"on {object_type!r}.",
            {"objectType": object_type, "field": spec.name}) from None


def _row_value(row: Mapping[str, Any], spec: FieldSpec) -> Any:
    raw = row.get(spec.name)
    if raw is None:
        return None
    try:
        return _typed(raw, spec.data_type)
    except (ValueError, TypeError, decimal.InvalidOperation):
        # A stored value that does not fit its declared type matches nothing.
        return None


def _ordered(operator: str, left: Any, right: Any) -> bool:
    try:
        if operator == "lt":
            return bool(left < right)
        if operator == "lte":
            return bool(left <= right)
        if operator == "gt":
            return bool(left > right)
        return bool(left >= right)
    except TypeError:
        return False


def compile_filter(node: FilterNode, view: SchemaView, object_type: str,
                   fields: "dict[str, FieldSpec]") -> Predicate:
    """A predicate over a row ({field: stored value}), checked against the
    caller's schema. Collects the fields it reads into `fields`."""
    if isinstance(node, Junction):
        parts = [compile_filter(child, view, object_type, fields) for child in node.children]
        if node.operator == "and":
            return lambda row: all(part(row) for part in parts)
        return lambda row: any(part(row) for part in parts)
    if isinstance(node, Not):
        inner = compile_filter(node.child, view, object_type, fields)
        return lambda row: not inner(row)

    spec = view.filterable(object_type, node.field)
    fields[spec.name] = spec
    where = {"objectType": object_type, "field": spec.name}

    if isinstance(node, IsNull):
        wanted = node.is_null
        return lambda row: (row.get(spec.name) is None) is wanted
    if isinstance(node, Text):
        if spec.data_type != "string" or spec.is_link:
            raise ObjectSetError(f"{node.operator} applies to text; field {spec.name!r} "
                                 f"on {object_type!r} is {spec.data_type}.", where)
        needle = node.value.casefold()
        if node.operator == "contains":
            return lambda row: (v := _row_value(row, spec)) is not None and needle in str(v).casefold()
        return lambda row: (v := _row_value(row, spec)) is not None and str(v).casefold().startswith(needle)
    if isinstance(node, In):
        wanted_values = [_filter_value(item, spec, object_type) for item in node.values]
        try:
            # A SET, so a row costs one lookup however many values there
            # are; coerced first because 1, 1.0 and Decimal(1) are one value.
            wanted_set = frozenset(wanted_values)
        except TypeError:
            wanted_set = None
        if wanted_set is not None:
            return lambda row: (v := _row_value(row, spec)) is not None and v in wanted_set
        return lambda row: (v := _row_value(row, spec)) is not None and any(v == item for item in wanted_values)
    # Compare
    if node.operator != "eq" and (spec.is_link or spec.is_id or spec.data_type not in _ORDERED_TYPES):
        kind = "a link" if spec.is_link else "the primary key" if spec.is_id else spec.data_type
        raise ObjectSetError(f"{node.operator} needs a field with an order; field {spec.name!r} "
                             f"on {object_type!r} is {kind}.", where)
    target = _filter_value(node.value, spec, object_type)
    if node.operator == "eq":
        return lambda row: (v := _row_value(row, spec)) is not None and v == target
    operator = node.operator
    return lambda row: (v := _row_value(row, spec)) is not None and _ordered(operator, v, target)


#: A link equality to hand to the search: (field, target type, values).
LinkCondition = tuple[str, str, tuple[str, ...]]


def _pushdown(node: FilterNode, view: SchemaView,
              object_type: str) -> "tuple[list[FieldFilter], list[LinkCondition]]":
    """The equality tests of a filter's top-level AND that the mediator
    can search for directly. ONLY a narrowing: the whole predicate is
    applied again afterwards, so this can make a search reach further
    (past the scan ceiling) and cannot make a result bigger. Text fields
    only, where SQL equality and the Python comparison cannot differ.

    A LINK is pushed down as a LinkCondition and resolved when the set runs:
    only the target ids the caller may read are handed to the search. The
    raw value must not be (a request naming a row the caller cannot see
    would narrow the result only if that row existed: a membership test),
    and a link that names only hidden rows is, as get_field() sees it, null
    on every row, so it matches nothing and needs no search at all."""
    conditions: list[FieldFilter] = []
    links: list[LinkCondition] = []
    if isinstance(node, Junction) and node.operator == "and":
        for child in node.children:
            more, more_links = _pushdown(child, view, object_type)
            conditions.extend(more)
            links.extend(more_links)
        return conditions, links
    if isinstance(node, (Compare, In)):
        if isinstance(node, Compare) and node.operator != "eq":
            return conditions, links
        spec = view.filterable(object_type, node.field)
        values = [node.value] if isinstance(node, Compare) else list(node.values)
        if spec.data_type == "string" and all(isinstance(v, str) for v in values):
            if not spec.is_link:
                conditions.append(FieldFilter(field=spec.name, operator="in", value=values))
            elif spec.target is not None:
                links.append((spec.name, spec.target, tuple(values)))
    return conditions, links


# ------------------------------------------------------------- evaluation

@dataclass
class Run:
    """What one evaluation needs, handed down rather than reached for."""

    mediator: Any
    user: Any
    context: Any
    visible: dict
    #: Some leaf stopped at the scan ceiling with the row check part of its
    #: query, so what it returned is a truncated ANSWER. See take().
    truncated: bool = False
    def take(self, ids: list, outcome: SearchOutcome) -> list:
        """Refuses a set it could not read completely.

        NEVER A SILENT CUT. When the mediator stopped at its scan ceiling:
        if the row check was part of the query (a `field:` security column,
        or a type with no row check) every row it scanned was visible, so
        the result is truncated and says so. Otherwise the scan is a mix of
        rows the caller can and cannot see, the visible part may be
        incomplete whatever its size, and reporting the mediator's flag
        would say how many hidden rows exist; the set is refused, in a
        sentence that names no count. v1 reports the mediator's flag as it
        is; this is v2's rule, and v1 is unchanged. (That the refusal
        itself turns on whether a scan went past the ceiling is a limit v1
        shares: BLOCKING.md, item 12.)

        THE REQUEST BUDGET IS NOT SPENT HERE. It is charged by prepare(),
        from the shape of the set alone, before any data is read.
        """
        if outcome.scan_truncated:
            if not outcome.row_check_pushed:
                raise ObjectSetError(TOO_LARGE_SENTENCE)
            self.truncated = True
        return ids


class Prepared:
    """A set checked against one caller's schema and ready to run."""

    object_type: str

    def ids(self, run: Run) -> list:  # pragma: no cover - interface
        raise NotImplementedError


class _BaseStep(Prepared):
    def __init__(self, object_type: str, conditions: "list[FieldFilter] | None" = None,
                 links: "list[LinkCondition] | None" = None):
        self.object_type = object_type
        self.conditions = conditions or []
        self.links = links or []

    def ids(self, run: Run) -> list:
        conditions = list(self.conditions)
        for field_name, target, values in self.links:
            readable = run.mediator.readable_subset(run.user, target, list(values), run.context)
            if not readable:
                return []  # every named target is hidden or absent: null on every row
            conditions.append(FieldFilter(field=field_name, operator="in",
                                          value=[str(object_id) for object_id in readable]))
        outcome = SearchOutcome()
        return run.take(list(run.mediator.search_object(
            run.user, self.object_type, conditions, visible_schema=run.visible,
            context=run.context, outcome=outcome)), outcome)


class _StaticStep(Prepared):
    def __init__(self, object_type: str, id_field: str, keys: tuple[str, ...]):
        self.object_type = object_type
        self.id_field = id_field
        self.keys = keys

    def ids(self, run: Run) -> list:
        if not self.keys:
            return []
        outcome = SearchOutcome()
        return run.take(list(run.mediator.search_object(
            run.user, self.object_type,
            [FieldFilter(field=self.id_field, operator="in", value=list(self.keys))],
            visible_schema=run.visible, context=run.context, outcome=outcome)), outcome)


class _FilterStep(Prepared):
    def __init__(self, child: Prepared, predicate: Predicate, fields: "dict[str, FieldSpec]"):
        self.object_type = child.object_type
        self.child = child
        self.predicate = predicate
        self.fields = fields

    def ids(self, run: Run) -> list:
        candidates = self.child.ids(run)
        if not candidates:
            return []
        rows = run.mediator.field_values_for_ids(
            run.user, self.object_type, candidates, list(self.fields), context=run.context)
        return [object_id for object_id in candidates if self.predicate(rows.get(str(object_id), {}))]


class _CombineStep(Prepared):
    def __init__(self, kind: str, children: list[Prepared]):
        self.object_type = children[0].object_type
        self.kind = kind
        self.children = children

    def ids(self, run: Run) -> list:
        sets = [self.children[0].ids(run)]
        for child in self.children[1:]:
            sets.append(child.ids(run))
        # KEYED BY TEXT, because the same object reaches here as 1 from one
        # read and "1" from another; the first set's spelling is kept.
        first = {str(object_id): object_id for object_id in sets[0]}
        others = [{str(object_id) for object_id in members} for members in sets[1:]]
        if self.kind == "union":
            merged = dict(first)
            for members in sets[1:]:
                for object_id in members:
                    merged.setdefault(str(object_id), object_id)
            return list(merged.values())
        if self.kind == "intersect":
            return [object_id for key, object_id in first.items() if all(key in other for other in others)]
        return [object_id for key, object_id in first.items() if not any(key in other for other in others)]


class _AroundStep(Prepared):
    def __init__(self, child: Prepared, link: str, target: str):
        self.object_type = target
        self.child = child
        self.link = link

    def ids(self, run: Run) -> list:
        sources = self.child.ids(run)
        outcome = SearchOutcome()
        return run.take(list(run.mediator.search_around_from(
            run.user, self.child.object_type, sources, self.link,
            context=run.context, outcome=outcome)), outcome)


def _cost(node: ObjectSet) -> int:
    """What evaluating a set may cost, in objects looked at, worked out from
    its SHAPE ALONE: a search leaf costs the scan ceiling whatever it finds,
    a static leaf costs its keys. Nothing here may depend on the data, or
    the refusal would tell a caller what exists (a budget charged by what
    each leaf considered refused a guessed id only if a hidden row had it)."""
    if isinstance(node, Base):
        return int(mediator_module.MAX_SEARCH_SCAN)
    if isinstance(node, Static):
        return len(node.primary_keys)
    if isinstance(node, Filter):
        return _cost(node.object_set)
    if isinstance(node, SearchAround):
        return _cost(node.object_set) + int(mediator_module.MAX_SEARCH_SCAN)
    return sum(_cost(member) for member in node.object_sets)


def prepare(node: ObjectSet, view: SchemaView) -> Prepared:
    """Checks a parsed set against the caller's schema, reading no data, and
    charges the request budget (MAX_SCANNED_ROWS) before anything runs."""
    if _cost(node) > MAX_SCANNED_ROWS:
        raise ObjectSetError(
            f"This request may read more than {MAX_SCANNED_ROWS} objects across its sets; "
            f"use fewer sets or narrow them.", {"limit": MAX_SCANNED_ROWS})
    return _prepare(node, view)


def _prepare(node: ObjectSet, view: SchemaView) -> Prepared:
    if isinstance(node, Base):
        view.require_type(node.object_type)
        return _BaseStep(node.object_type)
    if isinstance(node, Static):
        return _StaticStep(node.object_type, view.id_field(node.object_type), node.primary_keys)
    if isinstance(node, Filter):
        child = _prepare(node.object_set, view)
        fields: dict[str, FieldSpec] = {}
        predicate = compile_filter(node.where, view, child.object_type, fields)
        view.one_storage(child.object_type, list(fields))
        if isinstance(child, _BaseStep) and not child.conditions:
            child = _BaseStep(child.object_type, *_pushdown(node.where, view, child.object_type))
        return _FilterStep(child, predicate, fields)
    if isinstance(node, SearchAround):
        child = _prepare(node.object_set, view)
        return _AroundStep(child, node.link, view.link(child.object_type, node.link))
    members = [_prepare(member, view) for member in node.object_sets]
    if len({member.object_type for member in members}) != 1:
        raise ObjectSetError(f"A {node.kind} combines sets of ONE object type; these differ.")
    return _CombineStep(node.kind, members)


@dataclass
class Evaluated:
    object_type: str
    ids: list
    #: The mediator stopped at its scan ceiling somewhere: "we stopped
    #: looking", never "there is more for you".
    scan_truncated: bool = False


def evaluate(mediator: Any, user_record: Any, prepared: Prepared, view: SchemaView,
             context: Any = None) -> Evaluated:
    """The ids of a prepared set, every one of which passed check_access(),
    in the mediator's own order."""
    run = Run(mediator, user_record, context, view.visible)
    ids = prepared.ids(run)
    return Evaluated(prepared.object_type, ids, run.truncated)


def ordered(mediator: Any, user_record: Any, view: SchemaView, object_type: str, ids: list,
            order_by: tuple[OrderTerm, ...], context: Any = None) -> list:
    """The ids sorted by the terms, nulls last whichever way a term runs,
    ties settled by the key so a page boundary never moves. A field the
    caller cannot read is refused exactly as an unknown one is."""
    specs = [view.filterable(object_type, term.field) for term in order_by]
    view.one_storage(object_type, [spec.name for spec in specs])
    if not order_by or not ids:
        return sorted(ids, key=id_sort_key)
    rows = mediator.field_values_for_ids(
        user_record, object_type, ids, [spec.name for spec in specs], context=context)

    def comparable(object_id: Any, spec: FieldSpec) -> Any:
        return _row_value(rows.get(str(object_id), {}), spec)

    result = sorted(ids, key=id_sort_key)
    # STABLE SORTS, LAST TERM FIRST: the first term ends up dominant and
    # the key order is what remains for equal rows.
    for term, spec in reversed(list(zip(order_by, specs, strict=True))):
        present = [i for i in result if comparable(i, spec) is not None]
        missing = [i for i in result if comparable(i, spec) is None]
        # A key sorts as the number it is when it is only digits (id_sort_key).
        order = id_sort_key if spec.is_id else sort_key
        def key(object_id: Any, spec: FieldSpec = spec, order: Callable[[Any], Any] = order) -> Any:
            return order(comparable(object_id, spec))

        present.sort(key=key, reverse=term.descending)
        result = present + missing
    return result


def metric_fields(view: SchemaView, object_type: str, metrics: tuple[Metric, ...],
                  group_by: str | None) -> list[dict]:
    """The mediator's measure dicts, after checking every field is one the
    caller may read, and numeric where a number is needed."""
    if group_by is not None:
        grouping = view.filterable(object_type, group_by)
        if grouping.is_link:
            raise ObjectSetError(f"Field {group_by!r} on {object_type!r} is a link; group by "
                                 f"a data field.", {"objectType": object_type, "field": group_by})
    measures = []
    for metric in metrics:
        if metric.field is not None:
            spec = view.filterable(object_type, metric.field)
            if spec.is_link or spec.data_type not in _NUMERIC_TYPES:
                raise ObjectSetError(
                    f"A {metric.aggregate} metric needs a numeric field; {metric.field!r} on "
                    f"{object_type!r} is {'a link' if spec.is_link else spec.data_type}.",
                    {"objectType": object_type, "field": metric.field})
        measures.append({"name": metric.name, "aggregate": metric.aggregate, "field": metric.field})
    view.one_storage(object_type, [name for name in dict.fromkeys(
        [group_by, *(metric.field for metric in metrics)]) if name is not None])
    return measures
