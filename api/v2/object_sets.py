"""
object_sets.py  (POST /api/v2/objectSets/...: operate on a described set)

    loadObjects  {objectSet, select?, orderBy?, pageSize?, pageToken?}
                 -> the same page as GET /objects/{type}, for any set
    count        {objectSet}                  -> {"count"}
    aggregate    {objectSet, groupBy?, metrics}
                 -> {"data": [{"group": {field: value}, "metrics": {name: value}}]}

The set is the JSON union of core/ontology/object_sets.py. All three
evaluate it through the mediator, so a caller counts, loads and sums
only what it could search for; a count never includes a row the caller
cannot see, and a metric over a field the caller cannot read is refused
as if the field did not exist.

AGGREGATE covers one exact grouping (`groupBy: [{"field": "category"}]`,
at most one) and count, sum, min, max and avg over numeric fields -- the
code the existing /api/objects/{type}/aggregate runs. Group-by-range,
fixed width and duration, distinct counts and percentiles are not in
this slice.

These are POSTs that change nothing, the verb a body needs.
"""

import datetime
import decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from api.v2.context import Call, call
from api.v2.loading import evaluated_set, load_page, prepared_set, translated
from api.v2.problems import invalid_argument
from core.ontology.decimal_text import decimal_text
from core.ontology.mediator import security_cache_scope
from core.ontology.object_sets import (
    ObjectSetError,
    metric_fields,
    parse_metrics,
    parse_object_set,
    parse_order_by,
    parse_select,
)

router = APIRouter()


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objectSet: dict[str, Any]


class LoadObjectsRequest(_Request):
    select: list[str] | None = None
    orderBy: list[dict[str, Any]] | None = None
    pageSize: int | None = None
    pageToken: str | None = None


class CountRequest(_Request):
    pass


class AggregateRequest(_Request):
    groupBy: list[dict[str, Any]] | None = None
    metrics: list[dict[str, Any]]


@router.post("/objectSets/loadObjects")
def load_objects(body: LoadObjectsRequest, c: Call = Depends(call)) -> dict:
    with translated():
        node = parse_object_set(body.objectSet)
        order_by = parse_order_by(body.orderBy)
        select = parse_select(body.select)
    return load_page(c, node, body.objectSet, order_by=order_by, select=select,
                     page_size=body.pageSize, page_token=body.pageToken)


@router.post("/objectSets/count")
def count_objects(body: CountRequest, c: Call = Depends(call)) -> dict:
    with security_cache_scope(), translated():
        node = parse_object_set(body.objectSet)
        view, prepared = prepared_set(c, node)
        evaluated = evaluated_set(c, view, prepared)
    return {"count": len(evaluated.ids), "scanTruncated": evaluated.scan_truncated,
            "requestId": c.context.request_id}


def _plain(value: Any) -> Any:
    """A group or a metric as JSON: dates ISO 8601, decimals exact text."""
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return decimal_text(value)
    return value


def _group_field(raw: "list[dict[str, Any]] | None") -> str | None:
    if not raw:
        return None
    if len(raw) > 1:
        raise ObjectSetError("This API groups by one field at most.")
    grouping = raw[0]
    if grouping.get("type", "exact") != "exact" or set(grouping) - {"type", "field"}:
        raise ObjectSetError('Only an exact grouping, {"type": "exact", "field": ...}, '
                             "is available.")
    field_name = grouping.get("field")
    if not isinstance(field_name, str) or not field_name:
        raise ObjectSetError("A grouping needs `field`.")
    return field_name


@router.post("/objectSets/aggregate")
def aggregate(body: AggregateRequest, c: Call = Depends(call)) -> dict:
    with translated():
        node = parse_object_set(body.objectSet)
        metrics = parse_metrics(body.metrics)
        group_by = _group_field(body.groupBy)
    with security_cache_scope(), translated():
        view, prepared = prepared_set(c, node)
        measures = metric_fields(view, prepared.object_type, metrics, group_by)
        evaluated = evaluated_set(c, view, prepared)
        try:
            grouped = c.mediator.aggregate_measures(
                c.user, prepared.object_type, [], group_by, measures, members=evaluated.ids)
        except ValueError as error:
            # Everything the field and metric checks above let through that
            # the mediator still refuses is the caller's request, not a fault.
            raise invalid_argument(str(error)) from None
    data = [{"group": {} if group_by is None else {group_by: _plain(group)},
             "metrics": {name: _plain(value) for name, value in values.items()}}
            for group, values in grouped.items()]
    return {"data": data, "scanTruncated": evaluated.scan_truncated,
            "requestId": c.context.request_id}
