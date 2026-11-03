"""
context.py  (what every /api/v2 call starts from)

ONE DEPENDENCY, `call`, resolves in this order: the request id, then WHO
is asking (the same get_current_user every /api route uses, so the same
session cookie, the same disabled-account and must-change-password
checks), then WHICH CONFIGURATION answers (the same get_generation pin).
A route never reads the application state's generation: it takes the pinned generation
from here, so a reload landing mid-request cannot make two reads in one
request disagree (tests/unit/test_generation_pin.py scans this package
for exactly that).
"""

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request, Response

from api.auth_dependency import get_current_user
from api.generation_dependency import get_generation
from core.deployment_loader import DeploymentGeneration
from core.intermediate_layer.auth import UserRecord
from core.request_context import RequestContext


@dataclass(frozen=True)
class Call:
    request: Request
    user: UserRecord
    generation: DeploymentGeneration
    context: RequestContext

    @property
    def mediator(self) -> Any:
        return self.generation.mediator


def begin(request: Request, response: Response) -> RequestContext:
    """The request id, assigned before anything can fail, so an error
    from authentication carries it too. The same id the access decisions
    of this request are recorded under."""
    context = RequestContext.new()
    request.state.v2_request_id = context.request_id
    # Every /api/v2 answer is about the caller's own view.
    response.headers["Cache-Control"] = "no-store"
    return context


def call(request: Request, context: RequestContext = Depends(begin),
         user: UserRecord = Depends(get_current_user),
         generation: DeploymentGeneration = Depends(get_generation)) -> Call:
    return Call(request=request, user=user, generation=generation, context=context)
