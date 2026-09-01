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
  - 200: a real answer, synthesized from what was gathered. If
    AgentLoop hit its max_hops limit before finishing (result.
    hit_max_hops), synthesize_insight() is told explicitly -- the
    answer itself will say so, rather than reading like a complete
    result when the search may genuinely have been cut short. See
    core/llm/synthesis_prompt.py's possibly_incomplete parameter.
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

/logout-all revokes EVERY session for the calling user (self-service --
a lost device, not sure which token is compromised). /users/{username}/
logout-all does the same for an admin, targeting anyone -- gated by
manage:users, same as every other account-management action below.
Both call the SAME SessionStore.invalidate_all_sessions();
deliberately revokes ALL sessions including whichever one made the
request, not "all except this one" -- simpler, and matches the
project's "if in doubt, everyone re-authenticates" discipline.

/users/{username}/visible-schema is an admin debugging view --
DataMediator.visible_schema() already computes exactly "what can this
user see," this just exposes it for a target user instead of only ever
being used internally for the caller's own request. Lets an admin
verify a role actually grants what they think it grants, without
impersonating anyone.

/users/{username}/disable, /enable, and DELETE /users/{username} are
account lifecycle actions, all gated by manage:users. Disabling
invalidates existing sessions AND is checked fresh on every subsequent
request (see api/auth_dependency.py) -- it takes effect immediately,
not just against future logins. /login itself ALSO checks
is_user_disabled(), after the credential check, never before -- see
that route's own comment for why the ordering matters (a timing side
channel otherwise). Deletion clears the credential, the directory
entry, and every session in one atomic operation (core.user_directory.
delete_user()) -- a deleted account can never be left holding a
still-valid token. Deliberately NOT guarded against an admin disabling
or deleting their own account, or the last remaining admin -- a real,
intentionally out-of-scope simplification, not an oversight.

/writes/{write_id}/confirm is the SEPARATE, later request that actually
approves or rejects a proposed write. Looks the write up by ID AND the
confirming user's identity together (core.pending_write_store.
PendingWriteStore.pop() is uniform-denial -- wrong user, unknown ID,
and expired ID all produce the identical 404, never a distinguishing
message). Also runs on app.state.executor now, same as /query --
confirm_and_execute() stopped being "a single, already-atomic SQL
statement" once an update could span multiple storages (see
core/ontology/write_log.py's own module docstring): it can now be a
log INSERT, several sequential cross-file write_fields() calls under a
lock, and a log UPDATE, real I/O that could otherwise block the event
loop for meaningfully longer than intended.
"""

import asyncio
import logging
import threading

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.auth_dependency import get_current_user
from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import UserRecord, authorize
from core.llm.synthesis_prompt import synthesize_insight
from core.ontology.write_mediator import WriteMediator
from core.pending_write_store import PendingWriteStore

logger = logging.getLogger(__name__)

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
    credential_store = request.app.state.credential_store
    session_store = request.app.state.session_store
    user_directory = request.app.state.user_directory

    # Credential check ALWAYS runs first, unconditionally -- checking
    # is_user_disabled() before this and short-circuiting for a
    # disabled account would create a timing side channel (a disabled
    # account's login would return faster than a real password check,
    # leaking "this account exists and is disabled" through response
    # timing alone, even with an identical error message). Same timing-
    # safety principle verify_credential() itself already follows.
    if not credential_store.verify_credential(body.username, body.password):
        # Generic on purpose -- see module docstring.
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user_directory.is_user_disabled(body.username):
        # SAME message as a wrong password -- a disabled account must
        # not be distinguishable from one that simply doesn't exist or
        # was given the wrong password.
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = session_store.create_session(body.username)
    return LoginResponse(token=token)


@router.post("/logout", status_code=204)
def logout(request: Request, authorization: str | None = Header(default=None)) -> None:
    # Needs the RAW token (to delete that exact session), not a
    # resolved UserRecord -- the only route with this need, so it
    # parses the header itself rather than adding a second shape to
    # the shared auth dependency for one caller.
    if authorization is not None and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        request.app.state.session_store.invalidate_session(token)
    # No error even if the header was missing/malformed -- logging out
    # of a session that isn't valid anyway isn't a meaningful failure.


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, current_user: UserRecord = Depends(get_current_user)) -> None:
    # Self-service -- revokes EVERY session for the caller, including
    # whichever one made this request. See module docstring.
    request.app.state.session_store.invalidate_all_sessions(current_user.user_id)


@router.get("/users")
def list_users_route(request: Request, current_user: UserRecord = Depends(get_current_user)) -> list[dict]:
    _require_manage_users(request, current_user)
    return request.app.state.user_directory.list_users()


@router.post("/users", status_code=201)
def create_user_route(body: CreateUserRequest, request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> dict:
    _require_manage_users(request, current_user)

    try:
        request.app.state.user_directory.create_user(
            body.username, body.password, body.mac_value, body.role_name
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return {"status": "created", "username": body.username}


def _require_manage_users(request: Request, current_user: UserRecord) -> None:
    # Shared by every account-management route below -- one place for
    # the check, rather than five copies of the same three lines.
    roles = request.app.state.config.roles
    if not authorize(current_user, roles, "manage:users"):
        raise HTTPException(status_code=403, detail="Not authorized to manage users")


@router.get("/users/{username}/visible-schema")
def visible_schema_route(username: str, request: Request,
                          current_user: UserRecord = Depends(get_current_user)) -> dict:
    _require_manage_users(request, current_user)

    user_directory = request.app.state.user_directory
    if not user_directory.user_exists(username):
        raise HTTPException(status_code=404, detail=f"Unknown user {username!r}")

    target_record = user_directory.get_user_record(username)
    mediator = request.app.state.mediator
    return mediator.visible_schema(target_record)


@router.post("/users/{username}/logout-all", status_code=204)
def logout_all_for_user(username: str, request: Request,
                         current_user: UserRecord = Depends(get_current_user)) -> None:
    _require_manage_users(request, current_user)
    request.app.state.session_store.invalidate_all_sessions(username)


@router.post("/users/{username}/disable", status_code=204)
def disable_user_route(username: str, request: Request,
                        current_user: UserRecord = Depends(get_current_user)) -> None:
    _require_manage_users(request, current_user)
    try:
        request.app.state.user_directory.disable_user(username)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/users/{username}/enable", status_code=204)
def enable_user_route(username: str, request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> None:
    _require_manage_users(request, current_user)
    try:
        request.app.state.user_directory.enable_user(username)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/users/{username}", status_code=204)
def delete_user_route(username: str, request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> None:
    _require_manage_users(request, current_user)
    try:
        request.app.state.user_directory.delete_user(username)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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


@router.get("/me/visible-schema")
def my_visible_schema_route(request: Request, current_user: UserRecord = Depends(get_current_user)) -> dict:
    # The self-service counterpart to GET /users/{username}/visible-
    # schema above -- that one is an ADMIN debugging view (manage:
    # users required, targets ANY username); this one needs nothing
    # beyond a valid login, and always returns the CALLER's own view.
    # The real, concrete reason this exists: the new browse/search UI
    # (see /objects/{object_type}/search below) needs to know which
    # object types even exist and are visible BEFORE a person can pick
    # one to search -- there was no self-service way to ask that at
    # all before this route.
    mediator = request.app.state.mediator
    return mediator.visible_schema(current_user)


# Hard cap on how many search_object_free_text() matches get expanded
# into full result rows below -- a real, deliberate safety limit, not
# genuine pagination (there is no way to ask for "the next page" of
# results yet). Prevents a broad/empty query on a large table from
# triggering an unbounded number of get_object() calls (each already
# its own N-field loop of get_field() calls -- see DataMediator.
# get_object()'s own docstring), not just an unbounded RESPONSE size.
MAX_SEARCH_RESULTS = 50


@router.get("/objects/{object_type}/search")
def search_objects_route(object_type: str, request: Request, q: str = "",
                          current_user: UserRecord = Depends(get_current_user)) -> dict:
    # The human-facing browse/search endpoint -- DataMediator.search_
    # object_free_text() underneath, a forgiving CONTAINS match across
    # every field a real end user could plausibly recognize (name,
    # email, ...), not the model's own exact-match search_object()
    # step. No manage:users or other extra gate here, unlike /users/
    # {username}/visible-schema above -- this operates on the CURRENT,
    # logged-in user's own view, same pattern /query itself uses;
    # search_object_free_text() and get_object() below already enforce
    # every real RBAC/MAC decision internally, so there is nothing
    # further for this route to check on top.
    #
    # Each result includes a real, useful SUMMARY (every field that
    # actually participated in the search, via the SAME free_text_
    # searchable_fields() DataMediator itself used -- never a second,
    # independently-guessed set that could silently drift out of sync
    # with what was actually searched), not just a bare id the UI would
    # otherwise need a SEPARATE call per result to make sense of.
    mediator = request.app.state.mediator
    matching_ids = mediator.search_object_free_text(current_user, object_type, q)
    summary_fields = mediator.free_text_searchable_fields(current_user, object_type)

    capped_ids = matching_ids[:MAX_SEARCH_RESULTS]
    results = [
        {"id": object_id, "fields": mediator.get_object(current_user, object_type, object_id, summary_fields)}
        for object_id in capped_ids
    ]
    return {"results": results, "total_matches": len(matching_ids)}


@router.get("/objects/{object_type}/{object_id}")
def get_object_detail_route(object_type: str, object_id: str, request: Request,
                             current_user: UserRecord = Depends(get_current_user)) -> dict:
    # The Object View backend -- every field the CALLER can see for one
    # specific object, not just the free-text-searchable summary subset
    # above. Deliberately thin: visible_schema() already computes
    # "every field this user is granted," and get_object() already
    # fetches any given field list in one call (including LINK fields
    # -- get_field() already resolves those to the linked id(s), one
    # id for cardinality "one", a list for "many"). No new DataMediator
    # method needed at all; this endpoint is pure composition of two
    # things that already existed for other reasons.
    #
    # SECURITY: object_id is never trusted for anything beyond
    # constructing the get_object() call itself -- every real
    # authorization decision (RBAC per field, MAC per object) happens
    # INSIDE get_object() -> get_field() -> check_access(), exactly
    # once per field, the SAME mechanism every other read path in this
    # project already uses. A caller pointed at an object outside
    # their own MAC boundary, or a field they lack a grant for, gets
    # None back for it -- never a different code path, never a
    # shortcut around the real check.
    #
    # An UNKNOWN object_type, and a real object_type with a NONEXISTENT
    # or MAC-denied object_id, both resolve to the SAME shape: every
    # field null. Deliberate, not an oversight -- matches get_field()'s
    # own "unknown and denied look identical" security property (see
    # that method's own docstring), now extended to the whole object,
    # not just a single field. A real, considered trade-off, decided
    # explicitly with the user: knowing whether a SPECIFIC id exists,
    # even within a type the caller can otherwise see, is itself a
    # real enumeration primitive worth denying, not merely a REST-
    # idiom nicety to relax for a cleaner 404. NEVER "fix" this to a
    # 404 without re-reading this reasoning first.
    mediator = request.app.state.mediator
    visible = mediator.visible_schema(current_user)
    type_def = visible.get(object_type)
    if type_def is None:
        return {"id": object_id, "fields": {}}

    field_names = list(type_def["fields"].keys())
    fields = mediator.get_object(current_user, object_type, object_id, field_names)
    return {"id": object_id, "fields": fields}


class ProposeActionRequest(BaseModel):
    parameters: dict = {}


@router.get("/me/visible-action-types")
def my_visible_action_types_route(request: Request, current_user: UserRecord = Depends(get_current_user)) -> dict:
    # Self-service counterpart to GET /me/visible-schema above, same
    # pattern -- the browse/search UI needs to know which object TYPES
    # exist before a person can pick one; Stage 3's direct action
    # invocation (POST /actions/{action_type_name} below) needs to
    # know which ACTIONS exist, and what parameters each one declares,
    # before a person can be shown a button or a form for one at all.
    # WriteMediator.visible_action_types() already existed for the
    # model-facing prompt (core/llm/agent_step_prompt.py) -- this
    # route is pure composition, no new backend logic.
    write_mediator: WriteMediator = request.app.state.write_mediator
    return write_mediator.visible_action_types(current_user)


@router.post("/actions/{action_type_name}")
def propose_action_route(action_type_name: str, body: ProposeActionRequest, request: Request,
                          current_user: UserRecord = Depends(get_current_user)) -> JSONResponse:
    # Stage 3's real backend: direct, UI-driven action invocation, NOT
    # routed through the LLM at all. WriteMediator.propose_action()
    # already takes explicit, caller-supplied parameters -- it has
    # ZERO dependency on the agent loop or a model's own reasoning;
    # core/agent/agentic_loop.py's own propose_action step is just ONE
    # caller of this same method, not a prerequisite for it. Every
    # real authorization decision (RBAC via execute:, MAC per object,
    # submission_criteria) is enforced INSIDE propose_action() itself,
    # identically for both callers -- this route adds no security
    # logic of its own, and must never be tempted to.
    #
    # Returns the EXACT SAME "pending_write" response shape /query
    # already returns for a proposed write -- deliberately, so the
    # EXISTING PendingWriteCard.jsx component (built for the /query
    # path) can be reused completely unchanged for this one too. Two
    # phases, same as every other write path in this project: this
    # only PROPOSES: nothing is applied until a separate, later POST
    # /writes/{id}/confirm call, same real confirmation gate a model-
    # initiated write already goes through.
    #
    # ERROR HANDLING -- decided explicitly with the user, a real,
    # deliberate DEPARTURE from Palantir's own documented default
    # (verified directly, not assumed: Palantir's real docs state
    # action type metadata -- title, description, rules -- is visible
    # to every user with Ontology access by default, whether or not
    # they can actually execute it, and their real API returns
    # standard, differentiated HTTP status codes with specific
    # messages for permission failures). Elysium's OWN, already-
    # established posture is more conservative by DEFAULT -- unknown/
    # denied already look identical for objects and fields throughout
    # this project (see get_object_detail_route's own docstring) --
    # and this route extends that SAME posture to actions too, for
    # every role EXCEPT one holding discover:action_types (see
    # visible_action_types()'s own docstring for that grant's full
    # reasoning): such a role already sees the WHOLE action catalog
    # via GET /me/visible-action-types, so "unknown vs denied" is not
    # a new leak for them specifically -- the real reason this
    # generic-by-default design exists doesn't apply once someone
    # already has that visibility. For that role only, the real
    # exception message is surfaced, and PermissionError gets its own,
    # differentiated 403 (matching standard HTTP semantics and
    # Palantir's own real API, both safe to do ONLY because this
    # specific role isn't the audience the generic default protects).
    # Every OTHER role keeps the fully generic, undifferentiated
    # response exactly as before.
    write_mediator: WriteMediator = request.app.state.write_mediator
    try:
        pending_write = write_mediator.propose_action(current_user, action_type_name, body.parameters)
    except (ValueError, TypeError, PermissionError) as e:
        logger.warning(f"propose_action_route: {action_type_name!r} rejected for {current_user.user_id!r}: {e}")
        roles = request.app.state.config.roles
        if authorize(current_user, roles, "discover:action_types"):
            status_code = 403 if isinstance(e, PermissionError) else 400
            raise HTTPException(status_code=status_code, detail=str(e)) from e
        raise HTTPException(
            status_code=400,
            detail="That action could not be proposed. Check the action name and parameters, "
                   "and that you're authorized to perform it.",
        ) from e

    write_id = request.app.state.pending_writes.store(pending_write)
    return JSONResponse(
        status_code=202,
        content={
            "pending_write": {
                "id": write_id,
                "action_type_name": pending_write.action_type_name,
                "description": pending_write.description,
                "sub_writes": [
                    {
                        "object_type": sw.object_type, "object_id": sw.object_id,
                        "changes": sw.changes, "expected_current_values": sw.expected_current_values,
                    }
                    for sw in pending_write.sub_writes
                ],
            }
        },
    )


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
        request.app.state.mediator.audit_log.log_query_cancelled(
            current_user.user_id, body.query, len(result.gathered)
        )
        raise HTTPException(status_code=499, detail="Client disconnected")

    # THE re-verification -- see module docstring. Applies before
    # EITHER branch below.
    current_record_now = request.app.state.user_directory.get_user_record(current_user.user_id)
    if current_record_now != current_user:
        raise HTTPException(
            status_code=409,
            detail="Your permissions changed while this request was processing -- please try again",
        )

    if result.pending_write is not None:
        write_id = request.app.state.pending_writes.store(result.pending_write)
        # ALWAYS a list of sub_writes now, one entry or many -- matches
        # confirm_and_execute()'s own object_ids response shape (see
        # its own docstring: uniform representation, not a shape that
        # changes based on how much happened). object_type included on
        # each entry too -- the old flat "changes" dict never named
        # which object it belonged to at all, meaningless once a
        # response can describe more than one. expected_current_values
        # included too -- lets the UI show a real "old -> new"
        # transition per field, not just the new value in isolation;
        # empty for a "create" sub_write (nothing existed to have an
        # old value), which the UI treats as "nothing to show a
        # transition from," not an error. action_type_name (a real,
        # already-existing PendingWrite field, e.g. "TransferFunds")
        # included as a clean, separate label -- the UI shows this as
        # the primary identifier, not description, which is a full,
        # technical audit string (raw parameter dict syntax) never
        # designed as user-facing copy. ui/src/components/
        # PendingWriteCard.jsx updated to match -- a real, polished
        # multi-object confirmation UI, no longer deferred now that
        # TransferFunds exists as a real multi-object action to design
        # it against (see this file's own AI-notes at the bottom).
        return JSONResponse(
            status_code=202,
            content={
                "pending_write": {
                    "id": write_id,
                    "action_type_name": result.pending_write.action_type_name,
                    "description": result.pending_write.description,
                    "sub_writes": [
                        {
                            "object_type": sw.object_type, "object_id": sw.object_id,
                            "changes": sw.changes, "expected_current_values": sw.expected_current_values,
                        }
                        for sw in result.pending_write.sub_writes
                    ],
                }
            },
        )

    real_data = AgentLoop.filter_real_data(result.gathered)
    insight = await event_loop.run_in_executor(
        executor, synthesize_insight, synthesis_client, body.query, real_data, result.hit_max_hops
    )
    return QueryResponse(answer=insight)


@router.post("/writes/{write_id}/confirm")
async def confirm_write_route(write_id: str, body: ConfirmWriteRequest, request: Request,
                               current_user: UserRecord = Depends(get_current_user)) -> dict:
    store: PendingWriteStore = request.app.state.pending_writes
    pending = store.pop(write_id, current_user.user_id)
    if pending is None:
        # Uniform denial -- wrong user, unknown ID, and expired ID all
        # look identical. See module docstring.
        raise HTTPException(status_code=404, detail="Unknown or expired pending write")

    write_mediator: WriteMediator = request.app.state.write_mediator
    # Offloaded to the SAME executor /query uses -- no longer "a
    # single, already-atomic SQL statement," which used to be why this
    # ran synchronously on the request-handling thread. Once an update
    # spans multiple storages (see core/ontology/write_log.py's own
    # module docstring), this can now be a log INSERT, several
    # sequential cross-file write_fields() calls under a lock, and a
    # log UPDATE -- real, sequential I/O that could otherwise block
    # the event loop for meaningfully longer than intended. Caught by
    # directly tracing this call chain, not just reasoned about.
    executor = request.app.state.executor
    event_loop = asyncio.get_running_loop()
    outcome = await event_loop.run_in_executor(executor, write_mediator.confirm_and_execute, pending, body.approved)
    return outcome if outcome is not None else {"status": "rejected"}


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - GET /objects/{object_type}/{object_id} -- Stage 2 of the Palantir-
#   parity UI plan (Object View). Needed no new DataMediator method at
#   all -- pure composition of visible_schema() + get_object(), both
#   already built for other reasons. See this route's own, extensive
#   inline comment for the full security reasoning (the 200-with-
#   nulls design for a nonexistent/denied object, decided explicitly
#   with the user -- do not "fix" it to a 404).
#
#   A real routing collision was a genuine, verified concern going in
#   (this route and /objects/{object_type}/search above share the
#   same URL prefix) -- confirmed directly, both via a live curl
#   against a real running server AND a dedicated permanent test
#   (test_object_detail_and_search_routes_do_not_collide), that
#   Starlette correctly prioritizes the literal "search" path segment
#   (registered first) over treating it as a literal object_id.
#
#   Building this ALSO surfaced a real, separate gap: tests/
#   integration/test_api.py's own client fixture had only ever built
#   mediator.db, never risk.db/support.db -- fine for every earlier
#   test in that file, but this route is the first thing there to
#   fetch EVERY visible field for an object, including Customer.
#   risk_score (a real, granted MDO field backed by risk_sql). Fixed
#   by building all three silos data_silos.yaml actually declares, not
#   by avoiding the field in the new test -- a real, if narrow, gap in
#   the fixture, not something to route around.
#
# - GET /objects/{object_type}/search -- the first real API surface
#   for the human-facing, non-technical browse/search UI (Palantir's
#   own Object Explorer being the closest real-world analog, per a
#   real research + architecture conversation with the user). Thin
#   wrapper over DataMediator.search_object_free_text() +
#   free_text_searchable_fields() -- see that file's own AI-notes for
#   the fuller backend design. No manage:users or other extra gate,
#   deliberately: operates on the CURRENT, logged-in user's own view,
#   same pattern /query itself uses -- every real RBAC/MAC decision is
#   already enforced inside the mediator calls themselves.
#   MAX_SEARCH_RESULTS (50) is a real, deliberate SAFETY LIMIT, not
#   genuine pagination -- there is no "next page" mechanism yet; a
#   caller only ever learns there were MORE matches via total_matches
#   exceeding len(results), not how to fetch them.
#
#   GET /me/visible-schema -- added right after, once the new browse/
#   search frontend (ui/src/components/ObjectSearchPanel.jsx) revealed
#   a real, missing prerequisite: nothing let a non-admin ask "which
#   object types even exist for ME" before this -- GET /users/
#   {username}/visible-schema above is an ADMIN debugging view
#   (manage:users required, targets a NAMED username), not something
#   an ordinary end user could call for their own view. Same "operates
#   on the CURRENT user, no extra gate" pattern as the search route
#   just above. A real end-to-end user of both routes now exists (see
#   that frontend file's own AI-notes), not built speculatively ahead
#   of a consumer.
#
# - The pending-write response's "sub_writes" list -- and confirm_
#   write's own passthrough "object_ids" list -- used to only ever
#   contain ONE entry in practice, with no real multi-object action
#   to exercise the shape. TransferFunds (tests/integration/fixtures/
#   ontology_schema.yaml) closed that; ui/src/components/
#   PendingWriteCard.jsx now has real, polished multi-object
#   rendering (separate labeled sections per object) to match, built
#   and verified against it directly -- see that file's own AI-notes
#   for the full record.
# - This response was also extended with expected_current_values per
#   sub_write (a real field SubWrite already had, previously unused
#   here) so the UI can show a genuine "old -> new" transition per
#   changed field, not just the new value alone -- see PendingWriteCard.
#   jsx's own AI-notes for why that's a meaningfully stronger
#   confirmation, especially for something like a transfer.
