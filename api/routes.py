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

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.apps import visible_apps_for
from api.auth_dependency import get_current_user
from core.agent.agentic_loop import AgentLoop
from core.auth.auth_cookies import (
    SESSION_COOKIE_NAME,
    clear_csrf_cookie,
    clear_session_cookie,
    generate_csrf_token,
    set_csrf_cookie,
    set_session_cookie,
)
from core.intermediate_layer.auth import UserRecord, authorize
from core.llm.synthesis_prompt import synthesize_insight
from core.lock_store import LockStore
from core.ontology.write_mediator import WriteMediator
from core.pending_write_store import PendingWriteStore

logger = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


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


@router.post("/login", status_code=204)
def login(body: LoginRequest, request: Request, response: Response) -> None:
    credential_reader = request.app.state.credential_reader
    session_writer = request.app.state.session_writer
    user_directory = request.app.state.user_directory
    login_attempt_tracker = request.app.state.login_attempt_tracker

    # Checked BEFORE the real password verification below, but NEVER
    # used to short-circuit it -- see login_attempt_tracker.py's own
    # module docstring for the full reasoning. verify_credential()
    # below still runs UNCONDITIONALLY regardless of this result, so a
    # locked-out response takes exactly as long as a real wrong-
    # password one, never leaking "this account exists and has recent
    # failed attempts against it" through response timing alone.
    locked_out = login_attempt_tracker.is_locked_out(body.username)

    # Credential check ALWAYS runs first, unconditionally -- checking
    # is_user_disabled() before this and short-circuiting for a
    # disabled account would create a timing side channel (a disabled
    # account's login would return faster than a real password check,
    # leaking "this account exists and is disabled" through response
    # timing alone, even with an identical error message). Same timing-
    # safety principle verify_credential() itself already follows.
    credentials_valid = credential_reader.verify_credential(body.username, body.password)

    if locked_out:
        # Same generic message as every other failure below --
        # deliberately never distinguishable from a plain wrong
        # password. Not recorded as a NEW failure here -- already
        # locked out; another record wouldn't change the outcome.
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if not credentials_valid:
        login_attempt_tracker.record_failure(body.username)
        # Generic on purpose -- see module docstring.
        raise HTTPException(status_code=401, detail="Invalid username or password")

    if user_directory.is_user_disabled(body.username):
        # SAME message as a wrong password -- a disabled account must
        # not be distinguishable from one that simply doesn't exist or
        # was given the wrong password. Deliberately NOT recorded as a
        # rate-limit failure -- the password itself was genuinely
        # correct here, blocked by account status alone, a different
        # thing entirely from a guessing attempt.
        raise HTTPException(status_code=401, detail="Invalid username or password")

    login_attempt_tracker.record_success(body.username)
    token = session_writer.create_session(body.username)
    # Real, httponly cookie -- never returned in the JSON body at all;
    # doing both would defeat the entire point (see core/auth/
    # auth_cookies.py's own docstring). The CSRF cookie is
    # deliberately readable (NOT httponly) -- see that same module's
    # docstring for why, and api/csrf_middleware.py for how it's used.
    set_session_cookie(response, token)
    set_csrf_cookie(response, generate_csrf_token())


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    # Needs the RAW token (to delete that exact session), not a
    # resolved UserRecord -- the only route with this need, so it
    # reads the cookie directly rather than adding a second shape to
    # the shared auth dependency for one caller.
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token is not None:
        request.app.state.session_writer.invalidate_session(session_token)
    # No error even if the cookie was missing -- logging out of a
    # session that isn't valid anyway isn't a meaningful failure.
    clear_session_cookie(response)
    clear_csrf_cookie(response)


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, current_user: UserRecord = Depends(get_current_user)) -> None:
    # Self-service -- revokes EVERY session for the caller, including
    # whichever one made this request. See module docstring.
    request.app.state.session_writer.invalidate_all_sessions(current_user.user_id)


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


def _no_store(response: Response) -> None:
    # Shared by every /me/* route below (dependencies=[Depends(_no_store)])
    # -- each one returns session-specific data about the CALLER
    # specifically (their own profile, their own visible schema/apps/
    # action types), never something safe for a shared or intermediate
    # cache to persist and later hand back to a different person on
    # the same machine. Cache-Control: no-store is the real, current,
    # standard recommendation for exactly this class of response
    # (confirmed directly against current guidance, not assumed) --
    # matters most on a shared workstation, a realistic scenario for
    # an internal tool like this one, not a hypothetical.
    #
    # A real, standard FastAPI pattern, not a workaround: a route (or,
    # as here, a dependency) can declare a plain `response: Response`
    # parameter and set headers on it directly, while the route itself
    # still returns an ordinary dict for the body -- FastAPI merges
    # the two into the one, real response actually sent (confirmed
    # directly against FastAPI's own docs before using it this way).
    response.headers["Cache-Control"] = "no-store"


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
    request.app.state.session_writer.invalidate_all_sessions(username)


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


@router.get("/me", dependencies=[Depends(_no_store)])
def my_profile_route(current_user: UserRecord = Depends(get_current_user)) -> dict:
    # A real "who am I" endpoint -- confirmed directly against how
    # established identity platforms do this (OpenID Connect's own
    # UserInfo endpoint; Palantir Foundry's own real, documented GET
    # .../admin/users/getCurrent), not invented from scratch. Reuses
    # get_current_user() exactly like every other protected route --
    # no new auth logic, no new security surface. Returns the SAME
    # three UserRecord fields GET /users/{username}/visible-schema's
    # own sibling routes already expose about OTHER users to an admin
    # (see list_users() in core/user_directory.py for the matching
    # field names) -- this is just the self-service, CALLER-only
    # version of that same shape, gated by nothing more than being
    # logged in at all, the same as every other /me/* route.
    #
    # No "disabled" field -- unlike list_users()'s own response,
    # there's nothing meaningful to say here: get_current_user() itself
    # already rejects a disabled account with a 401 before this route
    # ever runs (see api/auth_dependency.py's own docstring), so a
    # disabled caller could never reach this line at all.
    return {
        "username": current_user.user_id,
        "role_name": current_user.role_name,
        "mac_value": current_user.security_value,
    }


@router.get("/me/visible-apps", dependencies=[Depends(_no_store)])
def my_visible_apps_route(request: Request, current_user: UserRecord = Depends(get_current_user)) -> list[dict]:
    # The shell's own nav, made real: which apps exist for THIS
    # specific caller, computed from their actual grants -- not a
    # hardcoded, always-shown list every logged-in user saw regardless
    # of what they could actually use (Admin, before this route
    # existed, was visible to everyone in the nav even though every
    # single action inside it was already, separately, gated server-
    # side by manage:users -- the button itself just never reflected
    # that). Matches the exact same discipline already applied to
    # action buttons (see discover:action_types/"executable" on
    # ObjectDetailPanel.jsx) -- never show a nav entry for something
    # the caller genuinely cannot use.
    #
    # `gating_permission` deliberately excluded from the HTTP response
    # itself -- a real, third finding of the exact same class as GET
    # /me/visible-schema's own and GET /me/visible-action-types' own
    # (see mediator.py's and this file's own AI-notes for both):
    # confirmed directly, not assumed, that no frontend code anywhere
    # reads `.gating_permission` off a visible-apps entry (a direct
    # grep found only a TYPE DECLARATION, never an actual read) --
    # this backend ALREADY does the real filtering (visible_apps_for()
    # itself, just above, already excludes any app the caller can't
    # use at all), so the raw internal permission-STRING NAME gating
    # each entry (e.g. "manage:users") has no legitimate reason to
    # travel to the browser at all. `gating_permission` stays a real,
    # needed field on VISIBLE_APPS/visible_apps_for() itself, though
    # -- that internal filtering logic genuinely reads it; only this
    # HTTP-facing shape excludes it, same "filter at the boundary, not
    # the shared internal source" pattern as both prior fixes.
    roles = request.app.state.config.roles
    return [{"name": app["name"], "path": app["path"]} for app in visible_apps_for(current_user, roles)]


@router.get("/me/visible-schema", dependencies=[Depends(_no_store)])
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


@router.get("/me/visible-action-types", dependencies=[Depends(_no_store)])
def my_visible_action_types_route(request: Request, current_user: UserRecord = Depends(get_current_user)) -> dict:
    # Self-service counterpart to GET /me/visible-schema above, same
    # pattern -- the browse/search UI needs to know which object TYPES
    # exist before a person can pick one; Stage 3's direct action
    # invocation (POST /actions/{action_type_name} below) needs to
    # know which ACTIONS exist, and what parameters each one declares,
    # before a person can be shown a button or a form for one at all.
    # WriteMediator.visible_action_types() already existed for the
    # model-facing prompt (core/llm/agent_step_prompt.py).
    #
    # EXPLICIT INCLUSION, not `{**action_def, ...}` -- a real, second
    # fix, alongside GET /me/visible-schema's own (see mediator.py's
    # own AI-notes for the first): a spread-then-override here would
    # have leaked `sub_writes` (each mutation's own literal "set
    # property X to parameter.Y" mechanical logic -- including things
    # like CreateCustomer silently auto-populating the MAC field from
    # user.security_value) out to any browser, unfiltered, over HTTP.
    # Confirmed directly, not assumed, that nothing real needs this
    # HERE: `affected_object_types` already, independently covers the
    # only legitimate "what does this action touch" need (a real,
    # separate, top-level key, never derived from sub_writes at all);
    # ActionForm.tsx, the real, only frontend consumer of this
    # response, never references sub_writes anywhere (confirmed by a
    # direct grep, not assumed); and the model's own real need for
    # sub_writes (agent_step_prompt.py's own _describe_actions(), for
    # object_type per sub-write) is entirely INTERNAL --
    # agentic_loop.py calls WriteMediator.visible_action_types()
    # directly, inside the same Python process, never through this
    # HTTP route or across the network at all. Same reasoning `check
    # in with the person before removing something with real,
    # confirmed use elsewhere` already correctly held THIS key back
    # from a same-commit fix as visible_schema()'s own -- resolved
    # once actually confirmed here, not assumed either way.
    #
    # "executable" is added HERE, at this HTTP layer, deliberately NOT
    # inside visible_action_types() itself -- that method's own return
    # shape is shared with the model-facing prompt path and has real,
    # existing tests asserting exact dict equality against the raw
    # action_type definition; this flag is a UI-only concern (which
    # actions can grow a real button, not just appear in a catalog),
    # with no reason to touch that shared, already-correct method or
    # its own callers/tests at all.
    #
    # For a role WITHOUT discover:action_types, every entry it sees is
    # already execute:-filtered (visible_action_types()'s own existing
    # behavior), so "executable" is always true there -- correct,
    # if redundant, information. Only meaningfully varies once
    # discover:action_types is held (see that grant's own docstring on
    # visible_action_types() for the full reasoning): a role can see
    # an action's shape without being able to invoke it, and the UI
    # needs to know which is which to decide whether to offer a
    # button at all (see ObjectDetailPanel.jsx's own comment).
    write_mediator: WriteMediator = request.app.state.write_mediator
    roles = request.app.state.config.roles
    visible = write_mediator.visible_action_types(current_user)
    return {
        action_name: {
            "affected_object_types": action_def["affected_object_types"],
            "parameters": action_def["parameters"],
            "executable": authorize(current_user, roles, f"execute:{action_name}"),
        }
        for action_name, action_def in visible.items()
    }


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
    # Checked BEFORE any real, expensive work below -- reject a caller
    # already over their own limit before the agent loop, or the real
    # LLM itself, ever spends any real work on this specific request.
    # NOT recorded as a new query here (see query_rate_limiter.py's own
    # docstring) -- a rejected request never actually ran one. Two
    # real, separate instances now, not one -- see core/auth/
    # query_rate_limiter.py's own module docstring (Reader/Writer,
    # extending core/internal_storage.py's own hierarchy); the check
    # genuinely only ever needs to read, the increment genuinely only
    # ever needs to write, and neither needs the other's capability.
    if request.app.state.query_rate_limiter_reader.is_rate_limited(current_user.user_id):
        raise HTTPException(status_code=429, detail="Too many queries -- please wait before trying again")
    request.app.state.query_rate_limiter_writer.record_query(current_user.user_id)

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


# --- Generic, resource-agnostic locking -- see core/lock_store.py's
# own module docstring for the full mechanism. Built as part of the
# app shell, not config-builder-specific -- resource_name is an
# arbitrary caller-supplied string, and this class has no knowledge
# of what it actually names. No manage:* gate on acquire/refresh/
# release/status -- any logged-in user may attempt to lock any named
# resource; whether that attempt is MEANINGFUL for a given resource
# (e.g. only a manage:deployment_config holder's attempt to lock the
# config draft actually matters) is entirely up to whichever future
# route consumes this lock for a real purpose, not this generic layer
# itself. force-release is the one exception -- see its own route.

class LockTokenRequest(BaseModel):
    token: str


@router.post("/locks/{resource_name}/acquire")
def acquire_lock_route(resource_name: str, request: Request,
                        current_user: UserRecord = Depends(get_current_user)) -> dict:
    lock_store: LockStore = request.app.state.lock_store
    result = lock_store.acquire(resource_name, current_user.user_id)
    if result is None:
        # Tells the caller WHO currently holds it -- not a security
        # leak, since GET /locks/{resource_name} below already exposes
        # the identical information to any logged-in caller; returning
        # it here too just saves a second round-trip for the common
        # "show me why this failed" UI case.
        status = lock_store.get_status(resource_name)
        raise HTTPException(status_code=409, detail={"message": "Resource is locked by another user", "lock": status})

    token, expires_at = result
    return {"token": token, "expires_at": expires_at.isoformat()}


@router.post("/locks/{resource_name}/refresh")
def refresh_lock_route(resource_name: str, body: LockTokenRequest, request: Request,
                        current_user: UserRecord = Depends(get_current_user)) -> dict:
    lock_store: LockStore = request.app.state.lock_store
    new_expires_at = lock_store.refresh(resource_name, current_user.user_id, body.token)
    if new_expires_at is None:
        # Uniform denial -- wrong token, wrong user, unknown resource,
        # and a genuinely already-expired lock all look identical to
        # the caller. Correct next move on this response is a fresh
        # acquire(), not a retry of refresh() -- see LockStore.refresh()'s
        # own docstring for why.
        raise HTTPException(status_code=409, detail="Lock not held, or already expired -- acquire a new one")
    return {"expires_at": new_expires_at.isoformat()}


@router.post("/locks/{resource_name}/release", status_code=204)
def release_lock_route(resource_name: str, body: LockTokenRequest, request: Request,
                        current_user: UserRecord = Depends(get_current_user)) -> None:
    lock_store: LockStore = request.app.state.lock_store
    released = lock_store.release(resource_name, current_user.user_id, body.token)
    if not released:
        raise HTTPException(status_code=404, detail="Lock not held by you")


@router.post("/locks/{resource_name}/force-release", status_code=204)
def force_release_lock_route(resource_name: str, request: Request,
                              current_user: UserRecord = Depends(get_current_user)) -> None:
    # The ONE route in this whole section with a permission gate --
    # see core/lock_store.py's own module docstring for why the check
    # belongs entirely here, at the caller, not inside LockStore.
    # force_release() itself.
    roles = request.app.state.config.roles
    if not authorize(current_user, roles, "manage:locks"):
        raise HTTPException(status_code=403, detail="Not authorized to force-release locks")

    lock_store: LockStore = request.app.state.lock_store
    released = lock_store.force_release(resource_name)
    if not released:
        raise HTTPException(status_code=404, detail="Resource is not currently locked")


@router.get("/locks/{resource_name}")
def lock_status_route(resource_name: str, request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> dict:
    lock_store: LockStore = request.app.state.lock_store
    status = lock_store.get_status(resource_name)
    if status is None:
        return {"locked": False}
    return {"locked": True, **status}


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - GET /me/visible-apps used to return VISIBLE_APPS' own entries
#   as-is, including `gating_permission` -- a real, THIRD finding of
#   the exact same class as GET /me/visible-schema's own and GET
#   /me/visible-action-types' own (see mediator.py's and this file's
#   own AI-notes above for both): the raw, internal permission-STRING
#   NAME gating each app (e.g. "manage:users") leaked out, unfiltered,
#   to any browser. This backend already does the real filtering
#   (visible_apps_for() itself already excludes any app the caller
#   can't use at all -- the STRING NAME of what gates it was never
#   needed by anything downstream), and confirmed directly, not
#   assumed, that no frontend code anywhere reads .gating_permission
#   off a visible-apps entry (a direct grep found only a TYPE
#   DECLARATION on the frontend's own VisibleApp interface, never an
#   actual read) -- that type updated to match (ui/src/Shell.tsx),
#   along with every real test fixture that constructed one
#   (ui/src/Shell.test.tsx). `gating_permission` stays a real, needed
#   field on VISIBLE_APPS/visible_apps_for() itself, though -- that
#   internal filtering logic genuinely reads it; only this HTTP-
#   facing shape excludes it now. A real, new, dedicated test added
#   (test_visible_apps_never_leaks_gating_permission, tests/
#   integration/test_api.py); confirmed meaningful via a real negative
#   control. Verified live too: a real, authenticated browser
#   session's own real fetch() confirmed the trimmed shape for all
#   three real apps (including Admin's own real "manage:users" grant,
#   fully absent from the response), and the real, rendered nav
#   itself still showed all three correctly -- zero functional loss.
# - GET /me/visible-action-types used to spread the FULL action_def
#   (`**action_def`) into its own response -- a real, confirmed
#   second security bug, found and fixed alongside GET /me/visible-
#   schema's own (see mediator.py's own AI-notes for the first): each
#   action's real `sub_writes` -- including the literal, mechanical
#   "set property X to parameter.Y" mutations logic, e.g.
#   CreateCustomer silently auto-populating the MAC field (region)
#   from user.security_value -- leaked out, unfiltered, to any
#   browser. Deliberately NOT fixed in the same commit as the first,
#   despite looking similar at a glance -- confirmed directly, not
#   assumed, that `sub_writes` genuinely differs from `storage`/
#   `security`: unlike those, sub_writes IS a real, used dependency
#   (agent_step_prompt.py's own _describe_actions() reads sub_writes
#   [*].object_type for the model-facing prompt), so a real, separate
#   check was needed before deciding this was actually safe to strip
#   from the HTTP-facing view too. Confirmed it was: that need is
#   entirely INTERNAL (agentic_loop.py calls WriteMediator.
#   visible_action_types() directly, inside the same Python process,
#   never through this route); `affected_object_types` already,
#   independently covers the only legitimate HTTP-facing "what does
#   this touch" need; and ActionForm.tsx, the real, only frontend
#   consumer, never references sub_writes anywhere (confirmed by a
#   direct grep). Now built with explicit inclusion (affected_object_
#   types/parameters/executable only), matching the exact same fix
#   already applied to visible_schema() itself. A real, new,
#   dedicated test (test_visible_action_types_never_leaks_sub_writes_
#   or_mutations, tests/integration/test_api.py) added specifically
#   because no existing test asserted on this route's own key-level
#   shape either; confirmed meaningful via a real negative control.
#   Verified live too: a real, authenticated browser session's own
#   real fetch() confirmed the trimmed shape, AND a real navigation
#   into ActionForm itself confirmed the UI still renders and
#   functions identically -- zero functional loss from the fix.
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
