"""
csrf_middleware.py  (stateless double-submit CSRF check, on every
state-changing request)

Real, structural context for WHY this exists at all, not just how:
moving the session token from localStorage to an httpOnly cookie
(core/auth/auth_cookies.py) closes the XSS-based token-theft gap that
motivated the move, but it opens a DIFFERENT one -- a cookie, unlike a
Bearer Authorization header, is attached by the browser AUTOMATICALLY
to every same-origin request, including ones a malicious, cross-site
page tricks the browser into making without the user's knowledge
(classic CSRF). elysium_session is set SameSite=Strict specifically to
block this at the browser level -- but SameSite alone was researched
directly (OWASP's own current CSRF Prevention Cheat Sheet) and found
NOT to be sufficient on its own: "This attribute should not replace
having a CSRF Token. Instead, it should co-exist with that token."
Real, concrete reasons SameSite alone can still fail: some browsers
still don't enforce it correctly, and an attacker can sometimes still
trigger a top-level navigation or pop-up window a browser treats as
"same-site" even though it originated from attacker-controlled logic
-- OWASP's own words: SameSite alone is "only a speedbump along the
road to exploitation" in that case. This middleware is the second,
independent layer -- see core/auth/auth_cookies.py's own docstring
for the full elysium_csrf cookie design.

MIDDLEWARE, deliberately, NOT a per-route Depends() -- a per-route
dependency can be silently forgotten on some future new route; global
middleware cannot be skipped by accident. This is the SAME lesson
already applied to core/auth/login_attempt_tracker.py's own design:
SlowAPI, researched there, was found to have a real, documented
production bug where its own rate limiter silently does nothing on
any route missing an explicit decorator. Applying uniformly here
avoids that exact class of mistake for CSRF instead.

The check itself is deliberately simple -- "does the X-CSRF-Token
header match the elysium_csrf cookie's own value" -- and needs NO
server-side storage of its own for this token specifically (the
stateless double-submit pattern). This works because of same-origin
policy, not because of anything server-side: a cross-site attacker
page can trick a victim's browser into SENDING elysium_session (a
cookie is ambient, attached automatically) but can never READ
elysium_csrf's own value to construct a matching header -- that
requires genuine, same-origin JavaScript, which only this app's own
frontend has.

EXEMPT: safe methods (GET/HEAD/OPTIONS -- never state-changing by
convention, and this project's own routes never violate that) and
POST /api/login specifically -- no session/CSRF cookie pair exists
yet at the moment someone is logging in; there is nothing yet to
double-submit.

Used by: api/app.py, registered as real middleware alongside
         add_security_headers -- see that file's own comment for why
         both live as module-level functions there.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from core.auth.auth_cookies import CSRF_COOKIE_NAME

CSRF_HEADER_NAME = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PATHS = frozenset({"/api/login"})


async def csrf_protect(request: Request, call_next: RequestResponseEndpoint) -> Response:
    if request.method in _SAFE_METHODS or request.url.path in _EXEMPT_PATHS:
        return await call_next(request)

    cookie_value = request.cookies.get(CSRF_COOKIE_NAME)
    header_value = request.headers.get(CSRF_HEADER_NAME)

    # Both missing/mismatched are the SAME failure -- no reason to
    # distinguish them for the caller (matches the uniform-denial
    # principle this project's own auth code already follows
    # elsewhere, e.g. session_store.py's own validate_session()).
    # Same {"detail": ...} JSON shape as every real HTTPException in
    # this project (see api/routes.py throughout) -- this is
    # middleware, not a route handler, so it can't just `raise
    # HTTPException(...)` the same way, but the frontend's own
    # error handling (api.js's own apiFetchOrThrow()) reads
    # body.detail regardless of which layer actually rejected the
    # request, and shouldn't need to know or care which one did.
    if not cookie_value or not header_value or cookie_value != header_value:
        return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})

    return await call_next(request)
