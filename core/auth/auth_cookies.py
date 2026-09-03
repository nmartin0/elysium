"""
auth_cookies.py  (set/clear the real, browser-facing session and CSRF
cookies)

The ONE place that knows the actual cookie names, flags, and lifetime
-- api/routes.py's login()/logout() call these rather than each
constructing a raw Set-Cookie header itself, same reasoning as
core/auth/session_store.py owning SESSION_LIFETIME as its own,
single, shared constant rather than a value re-typed at every call
site.

TWO cookies, deliberately different in one specific way:

- elysium_session: httponly=True. The real session token
  (session_store.py's own create_session() output). Never readable by
  JavaScript, by design -- this is the ENTIRE point of moving off
  localStorage: even a hypothetical future XSS bug cannot read this
  value at all. Sent automatically by the browser on every same-
  origin request; the frontend's own api.js no longer attaches an
  Authorization header manually.

- elysium_csrf: httponly=False, DELIBERATELY. This one MUST be
  readable by same-origin JavaScript -- it exists specifically so
  api.js can read its value and echo it back as a real request header
  (X-CSRF-Token) on every state-changing call. This is the
  "stateless double-submit" CSRF pattern: api/csrf_middleware.py's own
  validation is just "does the header match this cookie's own value,"
  nothing stored server-side for this token specifically (the SESSION
  token, separately, is real, stored, server-side state; this one
  doesn't need to be). It works because a cross-site attacker page
  cannot read a cookie set by this origin -- same-origin policy
  prevents that regardless of SameSite -- so it can never construct a
  matching header value, even in the SameSite-bypass edge cases
  SameSite alone doesn't fully cover (see api/csrf_middleware.py's own
  docstring for the full reasoning, decided explicitly with the user
  after researching OWASP's own current guidance on this exact
  combination).

secure flag -- see _cookie_secure() below. Defaults to True (the
production-safe choice) even when unset, deliberately NOT matching
resolve_runtime_paths()'s own "unset = local-dev-friendly default"
convention: a Secure-flagged cookie that never gets set locally
(browsers silently refuse to store it over plain HTTP) is a loud,
IMMEDIATELY obvious failure the first time anyone tries to log in --
every subsequent request looks logged-out, with no cookie ever
appearing in dev tools. A forgotten env var in a REAL, production
deployment shipping WITHOUT Secure would be a silent, much worse
failure -- the app would appear to work correctly while the session
cookie travels in the clear over any future accidental HTTP
connection. Fails loud-but-safe locally rather than quiet-but-
risky in production; local dev sets ELYSIUM_COOKIE_SECURE=false
explicitly, once, in its own environment.

Used by: api/routes.py's own login()/logout() routes only.
"""

import os
import secrets

from fastapi import Response

from core.auth.session_store import SESSION_LIFETIME

SESSION_COOKIE_NAME = "elysium_session"
CSRF_COOKIE_NAME = "elysium_csrf"

# int, not timedelta -- Response.set_cookie()'s own max_age expects
# whole seconds.
_MAX_AGE_SECONDS = int(SESSION_LIFETIME.total_seconds())


def _cookie_secure() -> bool:
    # Explicit, case-sensitive "false" is the ONLY way to opt out --
    # anything else (unset, a typo, "False", "0") stays on the safe
    # side. See this module's own docstring for why the default is
    # secure=True, not secure=False the way resolve_runtime_paths()'s
    # own env vars default to local-dev-friendly values.
    return os.environ.get("ELYSIUM_COOKIE_SECURE") != "false"


def generate_csrf_token() -> str:
    # secrets.token_urlsafe() -- same, real, cryptographically secure
    # generation as session_store.py's own create_session(), never
    # anything hand-rolled. A genuinely SEPARATE random value from the
    # session token itself, not derived from it -- the stateless
    # double-submit pattern doesn't need or want that coupling; see
    # this module's own docstring.
    return secrets.token_urlsafe()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=_MAX_AGE_SECONDS,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


def set_csrf_cookie(response: Response, csrf_token: str) -> None:
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        max_age=_MAX_AGE_SECONDS,
        httponly=False,  # see this module's own docstring -- deliberate
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    # Explicit httponly/secure/samesite here too, matching
    # set_session_cookie() exactly -- delete_cookie()'s own defaults
    # differ (samesite="lax"), and a mismatched clearing instruction
    # is the kind of small inconsistency worth avoiding on principle,
    # even though it isn't a real security gap on its own (this
    # response only ever tells the browser to expire the cookie, never
    # to set a new, persistent value with weaker protection).
    response.delete_cookie(
        key=SESSION_COOKIE_NAME, path="/", httponly=True, secure=_cookie_secure(), samesite="strict"
    )


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(
        key=CSRF_COOKIE_NAME, path="/", httponly=False, secure=_cookie_secure(), samesite="strict"
    )
