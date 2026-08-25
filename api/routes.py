"""
routes.py  (the actual HTTP endpoints)

/login is the ONE route with no auth dependency -- everything else
requires a valid session, resolved by api/auth_dependency.py's
get_current_user().

/login's failure is DELIBERATELY as generic as verify_credential()
itself already is -- "invalid username or password" regardless of
whether the username exists at all, same uniform-denial reasoning used
everywhere else in this project, just applied at the HTTP boundary
instead of inside core/.

/users (creating a new user) is gated by authorize(current_user, roles,
"manage:users") -- the SAME authorize() function every other RBAC
check in this project uses, not a separate "is_root" special case.
core/user_directory.create_user() itself performs no permission check
of its own; the route is responsible for checking BEFORE calling it,
same "gatekeeping stays at the boundary" pattern used throughout.

/query is read-only -- see api/app.py's docstring for why writes aren't
wired up yet.
"""

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel

from core.agent.agentic_loop import AgentLoop
from core.auth.credential_store import verify_credential
from core.auth.session_store import create_session, invalidate_session
from core.intermediate_layer.auth import authorize, UserRecord
from core.llm.synthesis_prompt import synthesize_insight
from core.user_directory import create_user
from api.auth_dependency import get_current_user

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    mac_value: str | None = None
    role_name: str


class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    answer: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request) -> LoginResponse:
    db_path = request.app.state.credentials_db_path
    if not verify_credential(db_path, body.username, body.password):
        # Generic on purpose -- see module docstring.
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_session(db_path, body.username)
    return LoginResponse(token=token)


@router.post("/logout", status_code=204)
def logout(request: Request, authorization: str | None = Header(default=None)) -> None:
    # Needs the RAW token (to delete that exact session), not a
    # resolved UserRecord -- the only route with this need, so it
    # parses the header itself rather than adding a second shape to
    # the shared auth dependency for one caller.
    if authorization is not None and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        invalidate_session(request.app.state.credentials_db_path, token)
    # No error even if the header was missing/malformed -- logging out
    # of a session that isn't valid anyway isn't a meaningful failure.


@router.post("/users", status_code=201)
def create_user_route(body: CreateUserRequest, request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> dict:
    roles = request.app.state.config.roles
    if not authorize(current_user, roles, "manage:users"):
        raise HTTPException(status_code=403, detail="Not authorized to manage users")

    db_path = request.app.state.credentials_db_path
    try:
        create_user(db_path, roles, body.username, body.password, body.mac_value, body.role_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "created", "username": body.username}


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, request: Request,
          current_user: UserRecord = Depends(get_current_user)) -> QueryResponse:
    loop: AgentLoop = request.app.state.loop
    synthesis_client = request.app.state.synthesis_client

    gathered = loop.run(current_user, body.query)
    real_data = AgentLoop.filter_real_data(gathered)
    insight = synthesize_insight(synthesis_client, body.query, real_data)

    return QueryResponse(answer=insight)
