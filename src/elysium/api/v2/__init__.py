"""
api/v2  (the standard, versioned read surface)

One module per resource, mounted by api/app.py under /api/v2 behind the
same authentication and generation pin as /api (api/v2/context.py). The
v1 routes are untouched; this is added beside them, and the UI keeps
using v1 until a later phase moves it.

NOT YET PUBLISHED: there is no /api/v2/openapi.json. /openapi.json is
disabled on purpose (api/app.py), and serving a v2 spec to authenticated
callers is a separate step that needs the same care about what a spec
names. Until then the routes are documented in their modules.
"""

from fastapi import APIRouter

from elysium.api.v2 import object_sets, objects, schema
from elysium.api.v2.problems import install_problem_handlers

router = APIRouter()
router.include_router(schema.router)
router.include_router(objects.router)
router.include_router(object_sets.router)

__all__ = ["install_problem_handlers", "router"]
