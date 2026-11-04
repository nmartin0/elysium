"""
loading.py  (turning an object set into a page of rows)

Shared by GET /objects/{type} and POST /objectSets/loadObjects, so the two
cannot differ on what a page is. Everything here goes through
core/ontology/object_sets.py, which goes through the mediator; this module
adds the wire shape and the paging, and no way to read anything.

A ROW is `{"objectType", "primaryKey", "properties"}`. The primary key is
always text (an id is text on every other route too). `properties` holds
exactly the fields `select` named, or by default only the type's title
field: select what you need. A field the caller cannot read, named in
`select`, is refused with the words used for a field that does not
exist.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from elysium.api.v2 import paging
from elysium.api.v2.context import Call
from elysium.api.v2.problems import ApiProblem, invalid_argument, invalid_page_token, not_found
from elysium.core.ontology.decimal_text import exact_decimals
from elysium.core.ontology.mediator import security_cache_scope
from elysium.core.ontology.object_sets import (
    Evaluated,
    ObjectSet,
    ObjectSetError,
    ObjectSetNotFound,
    OrderTerm,
    Prepared,
    SchemaView,
    evaluate,
    ordered,
    prepare,
)

#: What a caller is told when evaluating a set raised an error the checks
#: did not foresee. Fixed: the mediator's own text can name a hidden link or
#: the layout of a type's storage.
UNEVALUABLE_SENTENCE = "This request could not be evaluated."


@contextmanager
def translated() -> Iterator[None]:
    """The two ways a set can be refused, as the two ways the API answers.
    Any other ValueError is a 400 with a fixed sentence, never a 500 and
    never the mediator's words."""
    try:
        yield
    except ObjectSetNotFound:
        raise not_found() from None
    except ObjectSetError as error:
        raise invalid_argument(str(error), error.parameters) from None
    except ValueError:
        raise invalid_argument(UNEVALUABLE_SENTENCE) from None


def split_csv(values: "list[str] | None") -> tuple[str, ...]:
    """`?select=a,b&select=c` as ("a", "b", "c")."""
    names: list[str] = []
    for value in values or []:
        names.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(dict.fromkeys(names))


def checked_select(view: SchemaView, object_type: str, select: tuple[str, ...],
                   default_all: bool) -> list[str]:
    """The fields a row carries. Each must be one the caller may read.
    With none named: every readable field (one object), or the title
    field alone (a list)."""
    if select:
        return [view.selectable(object_type, name) for name in select]
    if default_all:
        return view.selectable_fields(object_type)
    title = view.title_field(object_type)
    return [title] if title else []


def row_of(call: Call, object_type: str, object_id: Any, fields: list[str]) -> dict[str, Any]:
    """One row. Each property is read through get_object(), so each is
    its own check_access() on the field and the object."""
    properties: dict[str, Any] = {}
    if fields:
        declared = (call.mediator.schema.get(object_type) or {}).get("fields") or {}
        properties = exact_decimals(
            call.mediator.get_object(call.user, object_type, object_id, fields,
                                     context=call.context), declared)
    return {"objectType": object_type, "primaryKey": str(object_id), "properties": properties}


def prepared_set(call: Call, node: ObjectSet) -> tuple[SchemaView, Prepared]:
    view = SchemaView(call.mediator, call.user)
    return view, prepare(node, view)


def evaluated_set(call: Call, view: SchemaView, prepared: Prepared) -> Evaluated:
    return evaluate(call.mediator, call.user, prepared, view, call.context)


def load_page(call: Call, node: ObjectSet, raw_query: Any, *, order_by: tuple[OrderTerm, ...],
              select: tuple[str, ...], page_size: int | None, page_token: str | None,
              default_all: bool = False) -> dict[str, Any]:
    """One page of a set. `raw_query` is whatever identifies the query
    (the wire form of the set, ordering and selection): a page token is
    bound to it."""
    key = paging.signing_key(call.request.app.state.runtime_paths.data_dir)
    query = paging.fingerprint(raw_query, [(t.field, t.descending) for t in order_by], list(select))
    offset = 0
    if page_token:
        try:
            offset = paging.redeem(key, page_token, call.user.user_id, query)
        except paging.InvalidToken:
            raise invalid_page_token() from None
    size = paging.page_size(page_size)

    with security_cache_scope(), translated():
        view, prepared = prepared_set(call, node)
        object_type = prepared.object_type
        fields = checked_select(view, object_type, select, default_all)
        for term in order_by:  # refused BEFORE anything is read
            view.filterable(object_type, term.field)
        view.one_storage(object_type, [term.field for term in order_by])
        evaluated = evaluated_set(call, view, prepared)
        ids = ordered(call.mediator, call.user, view, object_type, evaluated.ids, order_by,
                      call.context)
        page = ids[offset:offset + size]
        rows = [row_of(call, object_type, object_id, fields) for object_id in page]

    body: dict[str, Any] = {"data": rows, "totalCount": len(ids), "scanTruncated": evaluated.scan_truncated,
                  "requestId": call.context.request_id}
    if offset + size < len(ids):
        body["nextPageToken"] = paging.issue(key, call.user.user_id, query, offset + size)
    return body


__all__ = ["ApiProblem", "load_page", "translated", "split_csv", "checked_select", "row_of",
           "prepared_set", "evaluated_set"]
