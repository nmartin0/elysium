"""
schema.py  (GET /api/v2/schema: what THIS caller may know exists)

The permission-filtered schema, from the same DataMediator.visible_schema()
every other route asks, serialised through the same response model the
existing /api/me/visible-schema uses, so storage and security internals
stay out of it by the same mechanism. Two callers get different answers;
a type or field the caller was not told about is not in theirs.
"""

from typing import Any

from fastapi import APIRouter, Depends

from elysium.api.routes import VisibleObjectTypeResponse
from elysium.api.v2.context import Call, call

router = APIRouter()


@router.get("/schema")
def get_schema(c: Call = Depends(call)) -> dict[str, Any]:
    visible = c.mediator.visible_schema(c.user)
    return {"objectTypes": {
        name: VisibleObjectTypeResponse.model_validate(definition).model_dump()
        for name, definition in visible.items()}}
