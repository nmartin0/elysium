"""
problems.py  (/api/v2 errors: RFC 9457 problem details)

Every error under /api/v2 is `application/problem+json`:

    {"type": "/api/v2/problems/NotFound", "title": "Not found", "status": 404,
     "detail": "...", "errorName": "NotFound", "errorInstanceId": "<request id>",
     "parameters": {...}}

`errorName` is the stable, machine-readable name; `title` and `detail` are
for people and may change. `errorInstanceId` is the request id the call
carried (elysium.core.request_context), the same id GET /api/requests/{id}/trace
reads the access decisions back by, so a reported error names its trace.

UNIFORM DENIAL IS UNCHANGED, and is the reason there is one NotFound:
unknown, not permitted, expired and not-yours are the same 404 with the
same words. 401 means no valid session. 403 stays what it is today (a
capability refusal that reveals nothing, such as a password change being
required). A `parameters` member names only what the CALLER sent.

Only paths under /api/v2/ are affected: the handlers installed here hand
every other request to the handler that was there before.
"""

import uuid

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"
V2_PREFIX = "/api/v2/"
TYPE_PREFIX = "/api/v2/problems/"

_TITLES = {
    400: "Invalid argument",
    401: "Unauthenticated",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    413: "Request too large",
    429: "Too many requests",
}
_NAMES = {
    400: "InvalidArgument",
    401: "Unauthenticated",
    403: "Forbidden",
    404: "NotFound",
    405: "MethodNotAllowed",
    413: "RequestTooLarge",
    429: "TooManyRequests",
}


class ApiProblem(Exception):
    """An error with a status, a stable name and words for a person."""

    def __init__(self, status: int, error_name: str, detail: str, parameters: "dict | None" = None,
                 title: str | None = None):
        super().__init__(detail)
        self.status = status
        self.error_name = error_name
        self.detail = detail
        self.parameters = parameters or {}
        self.title = title or _TITLES.get(status, "Error")


def not_found() -> ApiProblem:
    """THE denial: the same words for unknown, forbidden and not-yours."""
    return ApiProblem(404, "NotFound", "No such resource.")


def invalid_argument(detail: str, parameters: "dict | None" = None) -> ApiProblem:
    return ApiProblem(400, "InvalidArgument", detail, parameters)


def invalid_page_token() -> ApiProblem:
    """One refusal for a token that is garbled, expired, for another
    query or another caller -- which of them it is would be a question."""
    return ApiProblem(400, "InvalidPageToken", "The page token is not valid for this request.")


def request_id_of(request: Request) -> str:
    # Set by elysium.api.v2.context.begin, the first thing every route does. A
    # request refused before that (a path that matched no route) still gets an id.
    existing = getattr(request.state, "v2_request_id", None)
    if existing is None:
        existing = str(uuid.uuid4())
        request.state.v2_request_id = existing
    return str(existing)


def problem_response(request: Request, status: int, error_name: str, detail: str,
                     parameters: "dict | None" = None, title: str | None = None) -> JSONResponse:
    body = {
        "type": TYPE_PREFIX + error_name,
        "title": title or _TITLES.get(status, "Error"),
        "status": status,
        "detail": detail,
        "errorName": error_name,
        "errorInstanceId": request_id_of(request),
        "parameters": parameters or {},
    }
    return JSONResponse(status_code=status, content=jsonable_encoder(body),
                        media_type=PROBLEM_MEDIA_TYPE, headers={"Cache-Control": "no-store"})


def _is_v2(request: Request) -> bool:
    return request.url.path.startswith(V2_PREFIX)


def install_problem_handlers(app: FastAPI) -> None:
    """Problem details for /api/v2, and the handlers already there for
    everything else. Call after the app's own handlers are registered."""
    previous_http = app.exception_handlers[StarletteHTTPException]
    previous_validation = app.exception_handlers[RequestValidationError]

    async def problem(request: Request, exc: Exception):
        assert isinstance(exc, ApiProblem)
        return problem_response(request, exc.status, exc.error_name, exc.detail, exc.parameters,
                                exc.title)

    async def http_error(request: Request, exc: Exception):
        assert isinstance(exc, StarletteHTTPException)
        if not _is_v2(request):
            return await previous_http(request, exc)
        status = exc.status_code
        # The words a v1 dependency raised (a 401's "Invalid or expired
        # session" is already uniform); a bare 404 from the router is the denial.
        detail = exc.detail if isinstance(exc.detail, str) and status != 404 else "No such resource."
        return problem_response(request, status, _NAMES.get(status, "Error"), detail)

    async def validation_error(request: Request, exc: Exception):
        assert isinstance(exc, RequestValidationError)
        if not _is_v2(request):
            return await previous_validation(request, exc)
        # Where and what, never the value that was sent.
        errors = [{"location": [str(part) for part in error["loc"]], "message": error["msg"]}
                  for error in exc.errors()]
        return problem_response(request, 400, "InvalidArgument",
                                "The request is not valid.", {"errors": errors})

    app.add_exception_handler(ApiProblem, problem)
    app.add_exception_handler(StarletteHTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
