"""
objects.py  (GET /api/v2/objects/{type} and /objects/{type}/{pk})

Reads only. There is no PUT, PATCH or DELETE on an object: a change is an
action, and actions arrive with their own resource.

LIST     ?pageSize ?pageToken ?select=a,b ?orderBy=amount:desc,name
         -> {"data": [row], "nextPageToken"?, "totalCount", "scanTruncated", "requestId"}
ONE      ?select=a,b       -> a row, every readable field by default

An unknown type, a type the caller may not read, and a key that does not
exist or that the caller may not read are one 404, NotFound, in the same
words. (The existing /api/objects/{type}/{id} answers an object it will
not show with nulls; this surface answers 404, as precedent does.)
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from elysium.api.v2.context import Call, call
from elysium.api.v2.loading import (
    checked_select,
    evaluated_set,
    load_page,
    prepared_set,
    row_of,
    split_csv,
    translated,
)
from elysium.api.v2.problems import not_found
from elysium.core.ontology.mediator import security_cache_scope
from elysium.core.ontology.object_sets import Base, Static, parse_order_by_text

router = APIRouter()


@router.get("/objects/{object_type}")
def list_objects(object_type: str, c: Call = Depends(call), pageSize: int | None = None,
                 pageToken: str | None = None, select: Annotated[list[str] | None, Query()] = None,
                 orderBy: str | None = None) -> dict:
    with translated():
        order_by = parse_order_by_text(orderBy)
    return load_page(c, Base(object_type), {"list": object_type}, order_by=order_by,
                     select=split_csv(select), page_size=pageSize, page_token=pageToken)


@router.get("/objects/{object_type}/{primary_key}")
def get_object(object_type: str, primary_key: str, c: Call = Depends(call),
               select: Annotated[list[str] | None, Query()] = None) -> dict:
    with security_cache_scope(), translated():
        view, prepared = prepared_set(c, Static(object_type, (primary_key,)))
        fields = checked_select(view, object_type, split_csv(select), default_all=True)
        found = evaluated_set(c, view, prepared).ids
        if not found:
            raise not_found()
        row = row_of(c, object_type, found[0], fields)
    return {**row, "requestId": c.context.request_id}
