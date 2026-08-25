"""
auth_dependency.py  (the one place a request's raw token becomes a real UserRecord)

Every route except /login goes through get_current_user() -- a FastAPI
Depends() that reads the Authorization header, resolves it to a
UserRecord, or raises a generic 401. Missing header, malformed header,
unknown token, expired token, AND a disabled account ALL produce the
EXACT SAME message -- the same uniform-denial principle used
throughout core/ (see core/ontology/mediator.py's docstring):
distinguishing any of these from each other would tell an attacker
something real, for zero benefit to a legitimate caller.

The disabled check happens HERE, on every single authenticated
request, checked fresh -- not just at login time. This is what makes
disabling an account take effect immediately against an EXISTING,
still-unexpired session token, not just block future logins. It runs
BEFORE get_user_record() resolves a real UserRecord -- a disabled
account never gets one at all, same as an invalid token.

Reads db_path/roles from request.app.state, set once at startup by
api/app.py's create_app() -- never re-derived here.

Used by: api/routes.py (every route requiring a logged-in caller)
"""

from fastapi import Header, HTTPException, Request

from core.auth.session_store import validate_session
from core.intermediate_layer.auth import UserRecord
from core.user_directory import get_user_record, is_user_disabled

_INVALID_SESSION_DETAIL = "Invalid or expired session"


def get_current_user(request: Request, authorization: str | None = Header(default=None)) -> UserRecord:
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail=_INVALID_SESSION_DETAIL)

    token = authorization.removeprefix("Bearer ")
    db_path = request.app.state.credentials_db_path

    username = validate_session(db_path, token)
    if username is None:
        raise HTTPException(status_code=401, detail=_INVALID_SESSION_DETAIL)

    if is_user_disabled(db_path, username):
        raise HTTPException(status_code=401, detail=_INVALID_SESSION_DETAIL)

    return get_user_record(db_path, username)
