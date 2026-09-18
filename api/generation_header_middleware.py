"""
Tells a client which configuration answered it.

THE PROBLEM. The UI fetches a user's visible schema ONCE, at login,
and never again -- useFetchOnLogin is exactly what its name says. A
configuration reload changes what the server will answer, and the
browser goes on believing what it was told at login.

FOUND BY USING IT. A field moved to `discover:` was correctly withheld
by the server, arriving as null, and the UI rendered it as "not set"
because its cached schema still said the field was readable. The right
answer -- "hidden by your permissions" -- only appeared after a manual
browser refresh.

It cuts both ways. A field a user has GAINED access to does not appear
either, and a role whose grants were revoked keeps seeing the field
names listed. That last one is confusion rather than disclosure: the
server withholds the values regardless, which is what makes this a
correctness-of-display bug and not a security one.

WHY A HEADER RATHER THAN POLLING. The client has no notion of
generations at all, so it cannot ask "has anything changed" without
inventing an endpoint and a timer. Every response already comes from
exactly one pinned generation, so stamping the number costs nothing
and lets the client notice on its NEXT request, whatever that is. No
poll, no socket, no new route.

WHY MIDDLEWARE RATHER THAN A DEPENDENCY. A dependency cannot set a
response header, and would only cover routes that declare it. This
covers every response, including ones added later by someone who has
never read this file.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

HEADER = b"x-elysium-generation"


class GenerationHeaderMiddleware:
    """Stamps the serving generation onto every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_generation(message: Message) -> None:
            if message["type"] == "http.response.start":
                # READ AT SEND TIME, not at request start. A reload
                # that completes mid-request should stamp the
                # generation the response was actually built from --
                # and api/generation_dependency.py pins that on
                # request.state, so this reads the pin rather than
                # app.state where one exists.
                generation = _serving_generation(scope)
                if generation is not None:
                    headers = message.setdefault("headers", [])
                    headers.append((HEADER, str(generation).encode("latin-1")))
            await send(message)

        await self.app(scope, receive, send_with_generation)


def _serving_generation(scope: Scope) -> "int | None":
    """The generation this response was built from, if one is known.

    NEVER RAISES. A missing generation means the app is still starting
    or this is a static file, and a header is not worth failing a
    response over -- the client treats an absent header as "no news".
    """
    state = scope.get("state") or {}
    pinned = state.get("generation")
    if pinned is not None:
        return getattr(pinned, "generation", None)

    app = scope.get("app")
    generation = getattr(getattr(app, "state", None), "generation", None)
    return getattr(generation, "generation", None)
