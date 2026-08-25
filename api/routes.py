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

/query runs on OUR OWN explicit executor (app.state.executor, see
api/app.py's docstring) via asyncio.run_in_executor(), not Starlette's
own internal thread pool. It has THREE possible outcomes:
  - 200: a real answer, synthesized from what was gathered.
  - 202 Accepted: the AI proposed a write. Nothing has happened to the
    data yet -- the response is a REFERENCE (a write_id), which
    /writes/{write_id}/confirm resolves later, in a genuinely separate
    request. 202 is the correct, standard status for exactly this
    shape ("request understood, not yet acted on, here's where to
    check"). See core/agent/agentic_loop.py's module docstring for why
    AgentLoop itself was changed to never confirm/execute a write on
    its own -- a synchronous pause for human approval mid-request has
    no meaning for a remote HTTP caller.
  - Cancelled early because the client disconnected mid-query: logged
    (log_query_cancelled), then raises a 499 (a widely-used, if
    unofficial, convention for "client closed the request") -- this
    response is never actually delivered to anyone (that's WHY it was
    cancelled), but the route still needs to return something
    well-formed rather than silently fall into logic that assumes the
    job completed normally. Disconnection is detected by a small
    concurrent watcher task polling request.is_disconnected() and
    setting a threading.Event AgentLoop.run() checks between hops --
    this does NOT stop the underlying background thread instantly
    (Python cannot safely force-kill a running thread from outside;
    confirmed against CPython's own issue tracker), only skips any
    FURTHER hops once the watcher notices -- bounded by the executor's
    fixed size and AgentLoop's own max_hops either way, so an abandoned
    job can't run unboundedly even in the worst case.

RE-VERIFICATION: a query can take a while (several LLM round-trips).
If the user's role or MAC value changes WHILE it's running (e.g. a
genuine access revocation), the results just gathered were computed
under permissions that are no longer current. Applies to BOTH the
"synthesize an answer" path AND the "return a pending write" path --
stale permissions shouldn't be acted on either way. Re-checks the
user's CURRENT record (a fast, direct database lookup, not offloaded
to the executor) against the UserRecord the job actually ran with,
using UserRecord's own dataclass equality rather than hand-rolled
field comparisons. Any mismatch refuses the whole response -- 409
Conflict, distinct from 401 (never authenticated) or 403 (never had
permission at all).

/writes/{write_id}/confirm is the SEPARATE, later request that actually
approves or rejects a proposed write. Looks the write up by ID AND the
confirming user's identity together (core.pending_write_store.
PendingWriteStore.pop() is uniform-denial -- wrong user, unknown ID,
and expired ID all produce the identical 404, never a distinguishing
message).
"""

import asyncio
import threading

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.agent.agentic_loop import AgentLoop
from core.auth.credential_store import verify_credential
from core.auth.session_store import create_session, invalidate_session
from core.intermediate_layer.audit import log_query_cancelled
from core.intermediate_layer.auth import authorize, UserRecord
from core.llm.synthesis_prompt import synthesize_insight
from core.ontology.write_mediator import WriteMediator
from core.pending_write_store import PendingWriteStore
from core.user_directory import create_user, get_user_record
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


class ConfirmWriteRequest(BaseModel):
    approved: bool


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


async def _watch_for_disconnect(request: Request, cancel_event: threading.Event) -> None:
    # Runs CONCURRENTLY with the executor-offloaded loop.run() call,
    # not racing it -- just sets cancel_event if it notices the client
    # is gone; AgentLoop.run() itself notices the event on its next hop
    # and returns early. Polling, not instant, but cheap and bounded.
    while not cancel_event.is_set():
        if await request.is_disconnected():
            cancel_event.set()
            return
        await asyncio.sleep(0.5)


@router.post("/query")
async def query(body: QueryRequest, request: Request,
                 current_user: UserRecord = Depends(get_current_user)):
    loop: AgentLoop = request.app.state.loop
    synthesis_client = request.app.state.synthesis_client
    executor = request.app.state.executor
    event_loop = asyncio.get_running_loop()

    cancel_event = threading.Event()
    watcher_task = asyncio.create_task(_watch_for_disconnect(request, cancel_event))
    try:
        result = await event_loop.run_in_executor(executor, loop.run, current_user, body.query, cancel_event)
    finally:
        cancel_event.set()
        watcher_task.cancel()

    if result.cancelled:
        log_query_cancelled(current_user.user_id, body.query, len(result.gathered))
        raise HTTPException(status_code=499, detail="Client disconnected")

    # THE re-verification -- see module docstring. Applies before
    # EITHER branch below.
    db_path = request.app.state.credentials_db_path
    current_record_now = get_user_record(db_path, current_user.user_id)
    if current_record_now != current_user:
        raise HTTPException(
            status_code=409,
            detail="Your permissions changed while this request was processing -- please try again",
        )

    if result.pending_write is not None:
        write_id = request.app.state.pending_writes.store(result.pending_write)
        return JSONResponse(
            status_code=202,
            content={
                "pending_write": {
                    "id": write_id,
                    "description": result.pending_write.description,
                    "changes": result.pending_write.changes,
                }
            },
        )

    real_data = AgentLoop.filter_real_data(result.gathered)
    insight = await event_loop.run_in_executor(
        executor, synthesize_insight, synthesis_client, body.query, real_data
    )
    return QueryResponse(answer=insight)


@router.post("/writes/{write_id}/confirm")
def confirm_write_route(write_id: str, body: ConfirmWriteRequest, request: Request,
                         current_user: UserRecord = Depends(get_current_user)) -> dict:
    store: PendingWriteStore = request.app.state.pending_writes
    pending = store.pop(write_id, current_user.user_id)
    if pending is None:
        # Uniform denial -- wrong user, unknown ID, and expired ID all
        # look identical. See module docstring.
        raise HTTPException(status_code=404, detail="Unknown or expired pending write")

    write_mediator: WriteMediator = request.app.state.write_mediator
    # A single, already-atomic SQL statement -- fast, not offloaded to
    # the executor the way the slow LLM calls are, same reasoning
    # already applied to get_user_record() above.
    outcome = write_mediator.confirm_and_execute(pending, body.approved)
    return outcome if outcome is not None else {"status": "rejected"}
