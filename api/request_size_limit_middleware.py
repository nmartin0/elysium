"""
request_size_limit_middleware.py  (rejects an oversized request body
before it ever reaches CSRF validation, auth, or a route handler)

Real, structural context for WHY this exists at all: a real, found gap
during a broader "backend is a kernel, frontend is userspace" audit --
this app had NO request body size limit anywhere, at all (confirmed
directly, not assumed -- neither FastAPI nor Starlette enforce one by
default; this is a real, still-open gap in the framework itself as of
this writing, not something this project overlooked configuring).
Elysium is a pure JSON API -- confirmed directly, not assumed, that no
route anywhere declares an UploadFile or otherwise expects a large
body -- so an arbitrarily large POST body (to ANY route, including
POST /login, the one route reachable with no authentication at all)
would previously have been read and buffered in full before anything
else even had a chance to reject it. A real, unauthenticated memory-
exhaustion vector, not a hypothetical.

A REAL ASGI MIDDLEWARE CLASS, deliberately NOT the simpler
`@app.middleware("http")` / `async def f(request, call_next)` style
csrf_protect and add_security_headers both use -- researched directly,
not assumed: that style already has real, documented buffering
behavior of its own before a request even reaches the wrapped
function's own body, which would defeat the entire point of a size
check by the time this code ever ran. Operating at the raw ASGI
`receive` level is what makes an accurate, real byte count possible at
all.

NEVER trusts the `Content-Length` header alone -- researched directly
against a real, production implementation of this exact pattern before
writing this: the header is only a real, useful FAST-PATH rejection (a
declared size already over the limit lets this middleware reject
before reading a single byte of body at all), never the sole check --
a missing, malformed, or deliberately UNDER-reported header (a client
lying about its own body's size, or omitting the header while still
streaming a huge chunked body) must never be able to bypass the limit.

THE REAL MECHANISM: read and buffer the ENTIRE real body FIRST,
counting genuine bytes as they arrive from the real, raw `receive`
channel, rejecting the instant the running total exceeds the limit --
BEFORE the wrapped downstream app is ever invoked at all. Only once
the full body is confirmed within the limit does this middleware
invoke the downstream app, with a real, wrapped `receive` that replays
the already-buffered messages first, then falls through to the real
channel for anything further. Deliberately NOT a design that starts
the downstream app first and tries to interrupt it mid-flight if the
limit is exceeded later -- ASGI doesn't cleanly support a second actor
sending a response once the downstream app may already have started
its own; buffer-validate-then-invoke sidesteps that whole class of
problem structurally, by construction, rather than needing to handle
it as a special case.

Only ever engages for a real HTTP scope (scope["type"] == "http") --
skips websocket/lifespan scopes entirely, matching every other real
ASGI-level check in this project.

A real 413 Request Entity Too Large -- the correct, standard HTTP
status for exactly this case -- with the SAME {"detail": ...} JSON
shape as every other real rejection in this project (see
csrf_middleware.py's own docstring on why that consistency matters:
the frontend's own error handling reads body.detail regardless of
which layer actually rejected the request).

DEFAULT_MAX_REQUEST_BODY_BYTES (1 MiB) -- confirmed directly, not
guessed, that this project is a pure JSON API with no file uploads
anywhere (a real grep for UploadFile/File(/multipart across every
route found zero matches): even the largest realistic real request
this app ever receives (a long natural-language query, or a
propose_action call with many parameters) would never reasonably
approach even a small fraction of this, so 1 MiB is genuinely
generous for real, legitimate traffic while still closing the real
gap for everything else.

Registered in api/app.py BETWEEN csrf_protect and add_security_headers
-- deliberately, not at either end. Starlette's own rule (confirmed
directly, empirically, not just from docs: registration order and
real execution order are exactly inverted -- verified with a real,
isolated middleware test before writing this, including the specific
three-way ordering used here) is that the LAST-registered middleware
becomes the OUTERMOST one, run FIRST on every real, incoming request.
Registered AFTER csrf_protect (so this runs BEFORE it -- an oversized
body is rejected before CSRF validation ever spends any real work on
it) but BEFORE add_security_headers (so add_security_headers stays the
true outermost layer and still wraps THIS middleware's own real 413
rejection too -- confirmed directly, via the same real test, that a
rejection from a middleware registered this way still passes back
through add_security_headers on its way out): every real response
this app ever sends, including a 413, carries the same, consistent
security headers -- no exception carved out for this one, specific
rejection path.

Used by: api/app.py
"""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DEFAULT_MAX_REQUEST_BODY_BYTES = 1_048_576  # 1 MiB


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int = DEFAULT_MAX_REQUEST_BODY_BYTES) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # The real, fast-path check -- a declared size already over
        # the limit means this middleware can reject BEFORE reading a
        # single real byte of body at all. Never the ONLY check (see
        # this module's own docstring for why), but genuinely worth
        # doing first: the common, honest case (a real client that
        # correctly reports its own body's size) is rejected as
        # cheaply as possible.
        declared_length = _declared_content_length(scope)
        if declared_length is not None and declared_length > self.max_body_bytes:
            await _reject_too_large(send)
            return

        # Read and buffer the REAL body now, counting genuine bytes as
        # they arrive -- this is what actually closes the gap a lying
        # or missing Content-Length header would otherwise leave open.
        buffered_messages: list[Message] = []
        received_bytes = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                # A real, if rare, non-body message (e.g. a disconnect
                # notification) -- buffer it unchanged, same as any
                # other message, so replay below stays faithful to
                # exactly what the real channel actually sent.
                buffered_messages.append(message)
                break

            received_bytes += len(message.get("body", b""))
            if received_bytes > self.max_body_bytes:
                await _reject_too_large(send)
                return

            buffered_messages.append(message)
            if not message.get("more_body", False):
                break

        await self.app(scope, _replay_receive(buffered_messages, receive), send)


def _declared_content_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                # A real, malformed header -- never trusted as a fast-
                # path signal either way; the real, byte-counted check
                # above is what actually decides in this case.
                return None
    return None


async def _reject_too_large(send: Send) -> None:
    response = JSONResponse(status_code=413, content={"detail": "Request body too large"})
    await response({"type": "http"}, _no_receive, send)


async def _no_receive() -> Message:
    # JSONResponse.__call__() itself never actually reads from
    # `receive` -- it only ever sends -- but Starlette's own Response
    # protocol requires a real, callable receive argument regardless;
    # this is a real, minimal, honest stand-in, never actually invoked
    # in practice, not a meaningful gap.
    raise RuntimeError("_no_receive() should never actually be awaited")


def _replay_receive(buffered_messages: list[Message], real_receive: Receive) -> Receive:
    # The already-buffered messages first, in their real, original
    # order -- then falls through to the REAL channel for anything
    # further (e.g. a genuine disconnect message arriving after the
    # body was already fully read) -- never re-reads or duplicates
    # anything already consumed above.
    remaining = list(buffered_messages)

    async def wrapped_receive() -> Message:
        if remaining:
            return remaining.pop(0)
        return await real_receive()

    return wrapped_receive
