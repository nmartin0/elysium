"""
auth_dependency.py  (the one place a request's session cookie becomes
a real UserRecord)

Every route except /login goes through get_current_user() -- a FastAPI
Depends() that reads the elysium_session cookie (see core/auth/
auth_cookies.py), resolves it to a UserRecord, or raises a generic
401. Missing cookie, unknown token, expired token, AND a disabled
account ALL produce the EXACT SAME message -- the same uniform-denial
principle used throughout core/ (see core/ontology/mediator.py's
docstring): distinguishing any of these from each other would tell an
attacker something real, for zero benefit to a legitimate caller.

Reads from a cookie, not an Authorization header -- the session token
moved to a real, httponly cookie specifically so client-side
JavaScript can never read it at all, even in a hypothetical future XSS
scenario (see core/auth/auth_cookies.py's own docstring for the full
reasoning). The browser attaches this cookie automatically on every
same-origin request; the frontend no longer manages this value itself.

The disabled check happens HERE, on every single authenticated
request, checked fresh -- not just at login time. This is what makes
disabling an account take effect immediately against an EXISTING,
still-unexpired session token, not just block future logins. It runs
BEFORE get_user_record() resolves a real UserRecord -- a disabled
account never gets one at all, same as an invalid token.

Reads the shared session_store/user_directory instances from
request.app.state, built once at startup by api/app.py's create_app()
-- never reconstructed or re-derived here.

Used by: api/routes.py (every route requiring a logged-in caller)
"""

from fastapi import Cookie, HTTPException, Request

from core.auth.auth_cookies import SESSION_COOKIE_NAME
from core.intermediate_layer.auth import UserRecord

_INVALID_SESSION_DETAIL = "Invalid or expired session"


def get_current_user(
    request: Request, session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME)
) -> UserRecord:
    if session_token is None:
        raise HTTPException(status_code=401, detail=_INVALID_SESSION_DETAIL)

    session_store = request.app.state.session_store
    user_directory = request.app.state.user_directory

    username = session_store.validate_session(session_token)
    if username is None:
        raise HTTPException(status_code=401, detail=_INVALID_SESSION_DETAIL)

    if user_directory.is_user_disabled(username):
        raise HTTPException(status_code=401, detail=_INVALID_SESSION_DETAIL)

    return user_directory.get_user_record(username)
