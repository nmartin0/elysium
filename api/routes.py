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
import base64
import functools
import json
import logging
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pyiceberg.catalog.sql import SqlCatalog

from api.apps import visible_apps_for
from api.auth_dependency import get_current_user
from api.generation_dependency import get_generation
from api.reload import ReloadInProgress, reload_generation
from core.agent.agentic_loop import AgentLoop
from core.auth.auth_cookies import (
    SESSION_COOKIE_NAME,
    clear_csrf_cookie,
    clear_session_cookie,
    generate_csrf_token,
    set_csrf_cookie,
    set_session_cookie,
)
from core.filters import FieldFilter, as_equality_conditions, parse_filters
from core.intermediate_layer.auth import UserRecord, authorize
from core.llm.synthesis_prompt import synthesize_insight
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.integrity import _row_count, check_mirror
from core.mirror.sync_attempts import SyncAttempts
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.mediator import SearchOutcome
from core.ontology.schema import get_field_column, sort_key
from core.ontology.submission_criteria import SubmissionCriteriaViolation
from core.ontology.write_mediator import MAX_BULK_OBJECTS, WriteMediator
from core.pending_write_store import PendingWriteStore
from core.request_context import RequestContext

logger = logging.getLogger(__name__)

router = APIRouter()

def _generation(request: Request):
    """The configuration this request is pinned to.

    Pinned ONCE per request by api/generation_dependency.py and cached
    on request.state; this reads that pin rather than app.state, so a
    reload landing mid-request cannot make two reads in one request
    disagree. Falls back to app.state for the small number of internal
    callers that construct a Request without going through the
    dependency -- notably the test client's own direct calls.
    """
    pinned = getattr(request.state, "generation", None)
    if pinned is not None:
        return pinned
    return get_generation(request)




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
    # The request this answer was built by, so the caller can ask what
    # was read to produce it. Returning it is what makes the trace
    # reachable -- an id the browser never sees is one nobody can look
    # up, and the endpoint would be dead surface.
    request_id: str


# --- Response models -------------------------------------------------
#
# Every route below declares a real `response_model`. This is NOT
# primarily about typing or documentation -- FastAPI's own OpenAPI
# generation is deliberately disabled in this project (see api/app.py,
# where docs_url/openapi_url are set to None after the full API surface
# was found readable without authentication). The reason is narrower
# and more important: `response_model` makes FastAPI FILTER the
# response, silently dropping any field the declared model does not
# name, before it ever reaches the caller.
#
# That converts "we remembered to filter" into "it is structurally
# impossible not to." This project has hit the un-filtered failure FOUR
# times: visible_schema()'s own storage config, visible_action_types()'
# sub_writes, visible-apps' gating_permission -- each fixed by hand --
# and then, found while writing these very models, per-field internals
# (storage/column/via_table/via_column, plus a data_type key added
# earlier in this same effort) still leaking one level down inside
# GET /me/visible-schema's own field dicts. A hand-written filter fixed
# the first three; nothing prevented the fourth. These models do.
#
# The real cost, stated plainly because it is easy to get wrong:
# filtering is SILENT. A model that omits a field the frontend actually
# uses breaks the UI with no error anywhere. Every model below was
# built against responses captured from a real, running server, and
# the field-level models specifically against a real grep of what the
# frontend genuinely reads -- not against what the code appeared to
# return.


class ProfileResponse(BaseModel):
    username: str
    role_name: str | None
    mac_value: str | None


class DataFreshnessResponse(BaseModel):
    source: str
    last_synced_at: str | None


class VisibleAppResponse(BaseModel):
    name: str
    path: str


class SchemaFieldResponse(BaseModel):
    # target/cardinality serialize as explicit nulls for a plain data
    # field. That is deliberate, and the lesser of two real evils:
    # Pydantic's exclude_none is all-or-nothing per RESPONSE, with no
    # per-model option (verified directly, not assumed), and applying
    # it here would also drop the enclosing type's own title_field
    # null -- which is a genuine SIGNAL, not absence. A null
    # title_field means "this type has one, but you cannot read it",
    # and ui/'s own format.ts documents depending on exactly that
    # distinction. Two extra nulls on a data field are harmless noise;
    # silently changing what a null title_field means is not. The
    # existing test suite caught this when the exclusion was applied
    # too broadly.
    # `type` tells a link from a data field; `target` and `cardinality`
    # resolve a link. storage, column, via_table and via_column stay
    # OUT -- they are physical layout with no legitimate reason to
    # reach a browser, and were genuinely leaking before this model
    # existed.
    #
    # data_type WAS grouped with them and should not have been. It is
    # SEMANTIC, not physical: "number" says nothing about where the
    # column lives, and it is precisely what the filter vocabulary
    # validates against. Without it a browser cannot tell which
    # operators a field accepts, so the filter bar offered `equals`
    # for everything -- more restrictive than the server, which allows
    # any operator on a field with no declared type.
    type: str
    # Whether this field's VALUE may be read. False is the middle rung:
    # the caller holds discover:{Type}.{field} and not read:, so they
    # may know the field exists and not what it holds, and a UI names
    # it while withholding the value.
    #
    # Defaulted to True so a response model without the key behaves as
    # every pre-ladder deployment did.
    readable: bool = True
    # Declared by the ontology, absent when it says nothing. A response
    # model that did not name it would strip it silently -- which is
    # exactly how `readable` shipped broken.
    decimal_places: int | None = None
    data_type: str | None = None
    target: str | None = None
    cardinality: str | None = None
    # The relationship this link field belongs to. Both ends of one
    # relationship carry the SAME link_type, and it is the only thing
    # joining them -- the API expands link types into per-type fields,
    # so without it a client cannot tell that Customer.transactions and
    # Transaction.customer_id are two ends of one link rather than two
    # unrelated fields. The schema browser's Link types view is built
    # on exactly this.
    #
    # Not internal config: it is the relationship's declared name, the
    # same one an ontology author wrote. The storage details beside it
    # -- via_table, via_column, via_target_column -- stay filtered out.
    link_type: str | None = None
    # Always present -- core/ontology/schema.py's humanize() supplies a
    # readable fallback when none is declared, so a UI never has to
    # decide what to render for an unlabelled field.
    display_name: str
    description: str | None = None
    # UI hints, always present with a default. "hidden" tells an
    # application not to SHOW this field; it does not stop anyone
    # reading it -- field-level RBAC is the only thing that does.
    visibility: str = "normal"
    status: str = "active"


class VisibleObjectTypeResponse(BaseModel):
    fields: dict[str, SchemaFieldResponse]
    # Whether this type may be SEARCHED, as opposed to merely known
    # about. False is the middle rung: the caller holds discover:{Type}
    # and not read:{Type}, so a search returns nothing and a UI should
    # say so rather than render "no matches" -- a claim about the data
    # when the truth is about their access.
    #
    # Defaulted, because a response model without it SILENTLY STRIPS
    # the key FastAPI is not told about. That is how this was missed:
    # the mediator was correct, every mediator-level test passed, and
    # the flag never survived serialisation.
    readable: bool = True
    id_field: str | None
    title_field: str | None
    # Matching Foundry's own object type metadata (displayName,
    # pluralDisplayName, description), in this project's snake_case.
    display_name: str
    plural_display_name: str
    description: str | None = None
    icon: str | None = None
    color: str | None = None
    status: str = "active"
    # A label for filtering and browsing a large ontology. Purely
    # organisational -- it groups nothing structurally.
    group: str | None = None


class ActionParameterResponse(BaseModel):
    # Mirrors SchemaFieldResponse's own reasoning for action parameters
    # -- ActionForm.tsx reads `type` (to pick an input control and to
    # spot an object_reference), `object_type`, `required`, and
    # `default_to_current_object`.
    type: str
    object_type: str | None = None
    required: bool | None = None
    default_to_current_object: bool | None = None
    # A parameter is what a person is asked to fill in. Without these
    # a form can only label it "new_from_balance".
    display_name: str | None = None
    description: str | None = None


class VisibleActionTypeResponse(BaseModel):
    affected_object_types: list[str]
    parameters: dict[str, ActionParameterResponse]
    executable: bool


class UserSummaryResponse(BaseModel):
    username: str
    mac_value: str | None
    role_name: str | None
    disabled: bool


class CreateUserResponse(BaseModel):
    status: str
    username: str


class MatchingIdsResponse(BaseModel):
    """Ids only, deliberately. A caller asking "what would select-all
    select" needs identity and nothing else, and returning whole
    objects would make an already-large response larger for no use."""

    object_ids: list[str]


class SearchResponse(BaseModel):
    results: list[dict[str, Any]]
    total_matches: int
    # THE ID THAT MAKES THE TRACE REACHABLE. Every access decision made
    # while serving this request carries it, and
    # GET /requests/{id}/trace reads them back -- but only if the
    # caller knows the id. Query already returns its own; Browse
    # recorded a trace nobody could ask for.
    request_id: str | None = None
    # Present only when there are more results -- see the route.
    next_page_token: str | None = None
    # THE SEARCH READ ITS CEILING AND STOPPED. It does NOT mean
    # "there is more for you": where MAC could not be pushed into
    # the query, the ceiling bounds a SCAN whose survivors are
    # filtered afterwards, so the rows beyond it might all have
    # been invisible anyway. The UI must say "we stopped looking",
    # never "there is more".
    scan_truncated: bool = False


class ObjectDetailResponse(BaseModel):
    id: str
    fields: dict[str, Any]
    # See SearchResponse: the trace is recorded either way, and this is
    # what lets a caller ask for it.
    request_id: str | None = None


class ConfirmWriteResponse(BaseModel):
    # object_ids is genuinely OPTIONAL, not defensive typing: this route
    # returns two real shapes. An APPROVED write returns
    # {"status": "written", "object_ids": [...]}; a REJECTED one returns
    # {"status": "rejected"} with no ids at all, because nothing was
    # written and there are no ids to report. Requiring it here made
    # every rejection a 500 -- caught by the existing test suite, which
    # is exactly the kind of behavior change response_model can
    # otherwise introduce silently.
    status: str
    object_ids: list[Any] | None = None


class ObjectSetQueryRequest(BaseModel):
    """Criteria selecting the object set an operation runs over.

    Mirrors Foundry's own aggregate API, where a `query` field "can be
    used to select which objects to aggregate" -- the set is chosen
    first, then the operation applies to it. An empty criteria dict
    means every object of the type the caller can see, which is a
    legitimate and common request rather than an error.
    """

    criteria: dict[str, Any] = {}

    # The full vocabulary, as a list of conditions. Present alongside
    # `criteria` rather than replacing it because they are not the same
    # request: `criteria` is equality on each key and cannot express
    # "region is us-west OR us-east", which is what selecting two
    # values on a chart means.
    #
    # A caller sends ONE of them. Sending both is rejected rather than
    # merged -- merging would need a rule for what happens when they
    # disagree about the same field, and inventing one silently is how
    # a filter ends up meaning something nobody asked for.
    conditions: list[dict[str, Any]] | None = None

    def as_conditions(self) -> list:
        """The filter this request asks for, however it was expressed.

        Field names are NOT validated here -- the mediator checks them
        against the caller's own visible schema, so a field they cannot
        read stays indistinguishable from one that does not exist. This
        only turns the wire form into the internal one.
        """
        if self.conditions is not None and self.criteria:
            raise ValueError(
                "Send either criteria or conditions, not both -- they are "
                "different requests and merging them would have to guess."
            )
        if self.conditions is not None:
            return parse_filters(self.conditions)
        return as_equality_conditions(self.criteria)


class AggregateRequest(ObjectSetQueryRequest):
    # Named to match Foundry's own vocabulary: an aggregation with an
    # optional groupBy. `field` is required for every aggregate except
    # count, which aggregates the set itself rather than a property.
    aggregate: str
    field: str | None = None
    group_by: str | None = None


class SearchAroundRequest(ObjectSetQueryRequest):
    link_field: str


class CountResponse(BaseModel):
    count: int


class AggregateResponse(BaseModel):
    # {group_value: metric}, with the group key stringified for JSON.
    # A None group (no group_by requested) becomes the empty string
    # rather than being dropped -- a caller asking for one aggregate
    # over the whole set must get a result back, not an empty object.
    results: dict[str, Any]


class SearchAroundResponse(BaseModel):
    ids: list[Any]
    total: int
    # SEE SearchResponse: the traversal stopped, which does NOT mean
    # there is more for this caller to see. Phase 0.2 capped the
    # SOURCE side of a search-around and left the fan-out unbounded --
    # ten thousand sources holding a hundred links each is a million
    # targets, and one audit line per target.
    scan_truncated: bool = False


class LinkCountResponse(BaseModel):
    target: str
    count: int
    cardinality: str | None = None


class LinkCountsResponse(BaseModel):
    # Keyed by link field name. A response model rather than a bare
    # dict because an undeclared key is SILENTLY STRIPPED by FastAPI --
    # the readable flag on visible_schema shipped broken for exactly
    # that reason, computed correctly and never serialised.
    links: dict[str, LinkCountResponse]


class EditHistoryEntryResponse(BaseModel):
    id: str
    operation: str
    changes: dict[str, Any]
    user_id: str
    description: str
    created_at: str
    # Present when the edit was part of a multi-object action, so a UI
    # can group the writes that happened together -- Foundry links a
    # single action log to every object it edited for the same reason.
    batch_id: str | None = None


class EditHistoryResponse(BaseModel):
    entries: list[EditHistoryEntryResponse]
    total: int
    next_page_token: str | None = None


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str]


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


@router.get("/users/{username}/visible-schema", response_model=dict[str, VisibleObjectTypeResponse])
def visible_schema_route(username: str, request: Request,
                          current_user: UserRecord = Depends(get_current_user)) -> dict:
    _require_manage_users(request, current_user)

    user_directory = request.app.state.user_directory
    if not user_directory.user_exists(username):
        raise HTTPException(status_code=404, detail=f"Unknown user {username!r}")

    target_record = user_directory.get_user_record(username)
    mediator = _generation(request).mediator
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


class AwaitingWriteResponse(BaseModel):
    """One proposal waiting for a decision.

    DELIBERATELY NOT THE CHANGED VALUES. A pending write names object
    ids and the fields it would set, and both are governed by MAC and
    field-level RBAC on every other read path. Returning them here
    because the caller happens to hold an execute grant would be a way
    around the read rules -- an approver could learn an account balance
    by proposing a write against it and listing their own inbox.

    So: what is being decided, by whom, and how long the reviewer has.
    The values are visible through the ordinary read path, subject to
    the ordinary checks, and a reviewer who cannot see them there
    should not see them here.
    """

    write_id: str
    action_type_name: str
    description: str
    proposed_by: str
    proposed_at: str
    object_count: int
    expires_at: str
    # WHETHER THIS IS YOURS TO DECIDE OR YOURS TO WAIT ON. A reviewer
    # and a proposer see the same row and need different things from
    # it, and a client that had to compare proposed_by against the
    # current user would be re-deriving something the server already
    # knows.
    #
    # Both can be true: nothing stops a deployment without a four-eyes
    # rule from letting someone approve their own write.
    awaiting_your_review: bool
    proposed_by_you: bool
    # Fields this write targets that the ontology no longer declares,
    # as "Type.field". Non-empty means it CANNOT be approved -- the
    # configuration moved on while it waited.
    #
    # A DIFFERENT STATE FROM REJECTED, which is what step 6c of
    # HOT_RELOAD_PLAN.md asks for: rejected means a human decided
    # against it, this means nobody can act on it either way. An inbox
    # that showed an Approve button here would let a reviewer make a
    # decision, learn it was refused, and have gained nothing.
    undeclared_fields: list[str]
    # THE INBOX FIELDS. A reviewer needs to know what they can act on
    # and what the request is still waiting for -- otherwise "approve"
    # looks like it will run the write, and for a request spanning
    # security partitions it will not.
    #
    # COUNTS, NOT THE TASKS THEMSELVES. A listing showing fifty task
    # rows per request would bury the requests, and the detail view
    # already loads a single write in full.
    tasks_total: int
    tasks_you_may_decide: int
    tasks_approved: int
    # How many OTHER pending writes propose exactly this change.
    #
    # SURFACED, NOT PREVENTED. A second identical proposal might be a
    # double-click, a colleague re-requesting something forgotten, or a
    # deliberate nudge, and Elysium cannot tell which. What was wrong
    # was that identical rows were INDISTINGUISHABLE -- a reviewer
    # could not tell one mistake pasted three times from three separate
    # requests, and approving one left the others behind unexplained.
    duplicate_count: int


@router.get("/writes/awaiting", dependencies=[Depends(_no_store)],
            response_model=list[AwaitingWriteResponse])
def awaiting_writes_route(request: Request,
                          current_user: UserRecord = Depends(get_current_user)) -> list[dict]:
    """Proposals this user may decide on.

    WITHOUT THIS, FOUR-EYES IS ENFORCEABLE AND UNREACHABLE. Confirming
    a write requires its id, and only the proposer had one -- so the
    single person who could find a write was the single person a
    four-eyes rule forbids from approving it.

    THE SAME ELIGIBILITY TEST THE CONFIRM ROUTE USES, so a listed write
    can always be claimed and a claimable write is always listed.
    Deciding them separately is how an inbox ends up showing rows that
    404, or silently hiding a decision somebody is waiting on.
    """
    roles = _generation(request).config.roles

    def may_confirm(candidate) -> bool:
        return authorize(current_user, roles, f"execute:{candidate.action_type_name}")

    def relevant(candidate) -> bool:
        # EITHER YOURS TO DECIDE OR YOURS TO WAIT ON, following
        # Foundry's inbox, which filters "Your inbox" and "Created by
        # you" rather than showing only one.
        #
        # A proposer needs the second especially once four-eyes is on:
        # they CANNOT approve their own write, so without this they
        # propose something and then have no way to see whether anyone
        # has looked at it. Nothing else in the product would tell
        # them, and a proposal that vanishes into silence is one people
        # stop making.
        return may_confirm(candidate) or candidate.user_id == current_user.user_id

    store: PendingWriteStore = request.app.state.pending_writes
    write_mediator = _generation(request).write_mediator
    waiting = store.awaiting(relevant)

    return [
        {
            "write_id": write_id,
            "action_type_name": pending.action_type_name,
            "description": pending.description,
            "proposed_by": pending.user_id,
            "proposed_at": pending.proposed_at.isoformat(),
            "object_count": len(pending.sub_writes),
            "expires_at": store.expires_at(write_id),
            "awaiting_your_review": may_confirm(pending),
            "proposed_by_you": pending.user_id == current_user.user_id,
            # THE SAME FUNCTION confirm_and_execute() uses, so the
            # inbox cannot disagree with what approving would actually
            # do. Computing it separately here is how a queue ends up
            # offering a button that always fails.
            "undeclared_fields": write_mediator.fields_no_longer_declared(pending),
            "tasks_total": len(pending.sub_writes),
            "tasks_you_may_decide": len(
                write_mediator.eligible_task_indexes(pending, current_user, roles)
            ),
            # APPROVED, not decided: a rejected task is not progress
            # toward invocation, and counting it as such would show a
            # request as nearly ready when it is permanently blocked.
            "tasks_approved": sum(
                1 for decision in store.task_decisions(write_id).values()
                if decision.approved
            ),
            "duplicate_count": store.duplicates_of(write_id),
        }
        # OLDEST FIRST. A reviewer works through a queue, and the write
        # closest to expiring is the one whose decision is about to be
        # taken away from them.
        for write_id, pending in sorted(waiting, key=lambda item: item[1].proposed_at)
    ]


class FieldChangeResponse(BaseModel):
    """One field a pending write would change.

    THE FIELD NAME IS ALWAYS PRESENT. Values are shown only where the
    reviewer may read them, and a field they may not read is marked
    REDACTED rather than omitted.

    That follows Foundry, whose review surfaces "redact certain
    resources or users contained in a record if you do not have the
    necessary permissions to view that item" -- and it is a deliberate
    reversal of an earlier design here that omitted such fields and
    reported only a boolean "something is hidden".

    Omitting leaks less and is worse. A reviewer seeing three fields
    cannot tell whether that is the whole change or a fragment, so they
    approve believing they saw everything -- the rubber-stamp problem
    in its worst form, because it produces MORE confidence rather than
    less. Redaction discloses that a field exists and withholds its
    value, which is the smaller cost: the reviewer already knows this
    write exists and which object it touches.
    """

    field_name: str
    # False means the reviewer lacks read:{Type}.{field}. The two value
    # fields are then null, and that is a REDACTION rather than a null
    # value in the data.
    readable: bool
    current_value: Any = None
    proposed_value: Any = None


class ObjectChangeResponse(BaseModel):
    object_type: str
    object_id: str
    operation: str
    changes: list[FieldChangeResponse]


class WriteDetailResponse(BaseModel):
    """Everything a reviewer needs to decide, and nothing more."""

    write_id: str
    action_type_name: str
    description: str
    proposed_by: str
    proposed_at: str
    expires_at: str
    awaiting_your_review: bool
    proposed_by_you: bool
    objects: list[ObjectChangeResponse]
    # Whether ANY field in this write is redacted for this reviewer.
    # Computed rather than derived by a client, so a UI cannot forget
    # to warn -- the one thing a reviewer must not miss is that they
    # are seeing a partial change.
    has_redacted_fields: bool


@router.get("/writes/{write_id}", dependencies=[Depends(_no_store)],
            response_model=WriteDetailResponse)
def write_detail_route(write_id: str, request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> dict:
    """What a pending write would actually change.

    SEPARATE FROM THE LISTING, because a diff needs the CURRENT value
    of every changed field, which means a gated read per field per
    object. A pending write can touch twenty objects; doing that for
    every row of an inbox would cost hundreds of reads to render a
    queue somebody is scanning rather than reading. Foundry splits it
    the same way -- the inbox lists requests, and you open one to see
    its tasks.

    THE SAME VISIBILITY RULE AS THE LISTING: you may see a write you
    could approve, or one you proposed. Anything else is a 404, not a
    403, matching the uniform denial every other path here uses.
    """
    generation = _generation(request)
    roles = generation.config.roles
    store: PendingWriteStore = request.app.state.pending_writes

    may_confirm_action = None
    pending = None
    for candidate_id, candidate in store.awaiting(lambda _pending: True):
        if candidate_id != write_id:
            continue
        may_confirm_action = authorize(
            current_user, roles, f"execute:{candidate.action_type_name}",
        )
        if may_confirm_action or candidate.user_id == current_user.user_id:
            pending = candidate
        break

    if pending is None:
        # Unknown, expired, and not-yours are one answer, deliberately.
        raise HTTPException(status_code=404, detail="Unknown or expired pending write")

    # WHAT THIS REVIEWER MAY READ, per type. visible_schema is already
    # the single source of truth for that question everywhere else, so
    # the diff asks it rather than re-deriving the grants.
    visible = generation.mediator.visible_schema(current_user)

    objects = []
    redacted_anywhere = False
    for sub_write in pending.sub_writes:
        readable_fields = set((visible.get(sub_write.object_type) or {}).get("fields") or {})
        changes = []
        for field_name, proposed in sub_write.changes.items():
            readable = field_name in readable_fields
            redacted_anywhere = redacted_anywhere or not readable
            changes.append({
                "field_name": field_name,
                "readable": readable,
                # The CURRENT value comes from the ordinary read path,
                # so MAC applies to the object as well as RBAC to the
                # field. A null here is indistinguishable from a
                # MAC-denied object, which is the same uniform denial
                # every other read gives and is deliberate.
                "current_value": generation.mediator.get_field(
                    current_user, sub_write.object_type, sub_write.object_id, field_name,
                ) if readable else None,
                # Gated identically. A field you may not read is a
                # field whose PROPOSED value you may not read either --
                # otherwise proposing a write would be a way to learn
                # what you are about to be told.
                "proposed_value": proposed if readable else None,
            })
        objects.append({
            "object_type": sub_write.object_type,
            "object_id": str(sub_write.object_id),
            "operation": sub_write.operation,
            "changes": changes,
        })

    return {
        "write_id": write_id,
        "action_type_name": pending.action_type_name,
        "description": pending.description,
        "proposed_by": pending.user_id,
        "proposed_at": pending.proposed_at.isoformat(),
        "expires_at": store.expires_at(write_id),
        "awaiting_your_review": bool(may_confirm_action),
        "proposed_by_you": pending.user_id == current_user.user_id,
        "objects": objects,
        "has_redacted_fields": redacted_anywhere,
    }


class ConfirmWriteRequest(BaseModel):
    approved: bool


@router.post("/login", status_code=204)
def login(body: LoginRequest, request: Request, response: Response) -> None:
    credential_store = request.app.state.credential_store
    session_store = request.app.state.session_store
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
    credentials_valid = credential_store.verify_credential(body.username, body.password)

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
    token = session_store.create_session(body.username)
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
        request.app.state.session_store.invalidate_session(session_token)
    # No error even if the cookie was missing -- logging out of a
    # session that isn't valid anyway isn't a meaningful failure.
    clear_session_cookie(response)
    clear_csrf_cookie(response)


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, current_user: UserRecord = Depends(get_current_user)) -> None:
    # Self-service -- revokes EVERY session for the caller, including
    # whichever one made this request. See module docstring.
    request.app.state.session_store.invalidate_all_sessions(current_user.user_id)


@router.get("/users", response_model=list[UserSummaryResponse])
def list_users_route(request: Request, current_user: UserRecord = Depends(get_current_user)) -> list[dict]:
    _require_manage_users(request, current_user)
    return request.app.state.user_directory.list_users()


class DeploymentConfigResponse(BaseModel):
    """What this deployment is actually running.

    READ-ONLY, and deliberately so. Editing config at runtime is a
    separate question with its own preconditions; this is the half
    that carries no risk and answers "why is it behaving like that".
    """

    llm_provider: str
    step_model: str
    synthesis_model: str
    max_hops: int
    max_consecutive_duplicates: int
    max_consecutive_invalid_steps: int
    max_concurrent_requests: int
    # WHICH configuration this is, not just what it says. Answers a
    # question the rest of this response cannot: two deployments with
    # identical settings below may still be different loads of
    # different files. Once configuration can be reloaded while running
    # (HOT_RELOAD_PLAN.md) this becomes the only way to tell which
    # generation served a given request.
    #
    # The digest is over the four config files' bytes. Safe to expose
    # alongside the rest of this response: it discloses WHETHER the
    # files changed, never what is in them, and this endpoint already
    # requires manage:users.
    generation: int
    loaded_at: str
    source_digest: str
    security_attribute: str
    read_from_mirror: bool
    enabled_tools: list[str]
    silo_names: list[str]
    object_type_count: int
    action_type_count: int
    role_names: list[str]


class ReloadResponse(BaseModel):
    """The outcome of a configuration reload."""

    from_generation: int
    to_generation: int
    source_digest: str
    changed: bool


@router.post("/admin/reload", response_model=ReloadResponse)
def reload_route(request: Request,
                 current_user: UserRecord = Depends(get_current_user)) -> dict:
    """Reloads configuration from disk without restarting.

    GATED ON manage:deployment, a SEPARATE grant from manage:users.
    Creating an account and replacing the ontology, the grants and the
    silo wiring are different powers, and a deployment should be able
    to hand out one without the other.

    FAILURE CHANGES NOTHING. build_generation() validates fully and
    either returns a whole generation or raises, so a broken YAML edit
    is a 400 with the validation error rather than an outage. That is
    strictly better than today, where the only way to load new
    configuration is to restart -- and a restart with a broken file
    does not come back.

    Requests already in flight keep the generation they pinned and
    finish on it. The next request gets the new one.
    """
    generation = _generation(request)
    if not authorize(current_user, generation.config.roles, "manage:deployment"):
        raise HTTPException(status_code=403, detail="Not authorized to reload configuration")

    try:
        new = reload_generation(request.app, requested_by=current_user.user_id)
    except ReloadInProgress as e:
        # 409, not 429: this is a conflict with another operation, not
        # a rate limit. Rejected rather than queued -- see
        # reload_generation() for why.
        raise HTTPException(status_code=409, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Reload rejected: {e}") from e

    return {
        "from_generation": generation.generation,
        "to_generation": new.generation,
        "source_digest": new.source_digest,
        # Whether the FILES actually differ, as opposed to whether a
        # reload happened. Reloading unchanged files is a new
        # generation of the same configuration, and conflating the two
        # would make "did anything change?" unanswerable.
        "changed": new.source_digest != generation.source_digest,
    }


class GenerationSummary(BaseModel):
    generation: int
    loaded_at: str
    source_digest: str


class SlowRouteResponse(BaseModel):
    route: str
    requests: int
    # NULL WHEN NOTHING SUCCEEDED in the window. Zero would read as
    # "instantaneous", which is the opposite of "we do not know".
    p99_ms: float | None = None


class MetricsResponse(BaseModel):
    """RED over a window: Rate, Errors, Duration.

    Saturation -- the fourth golden signal -- is deliberately absent:
    it is a property of the host, not of this process.
    """

    window_seconds: int
    requests: int
    rate_per_second: float
    # A RATIO, NOT A COUNT: ten failures means nothing without knowing
    # whether there were twelve requests or twelve thousand.
    error_ratio: float
    p50_ms: float | None = None
    p99_ms: float | None = None
    slowest_routes: list[SlowRouteResponse]


class ConfigHistoryResponse(BaseModel):
    """Which configurations this deployment has run.

    SUMMARIES ONLY -- no file contents. The files carry silo hosts,
    paths and credential references, which the /config route already
    declines to return for exactly that reason. Listing what ran is a
    different disclosure from handing over what it said.
    """

    current_generation: int
    generations: list[GenerationSummary]


def _recent_snapshots(catalog, identifier: str, limit: int = 5) -> list[dict]:
    """The newest snapshots of one table, newest first.

    READ FROM METADATA, not by scanning. Iceberg records a snapshot per
    commit with its timestamp, operation and row count, so this is
    history the mirror already holds.

    A TABLE THAT CANNOT BE READ RETURNS NOTHING rather than raising.
    This decorates a panel; a missing history should cost its own row
    and not the screen, and `check_mirror` is what reports a table
    that has genuinely gone.
    """
    from datetime import UTC, datetime

    try:
        table = catalog.load_table(identifier)
        current = table.current_snapshot()
        current_id = current.snapshot_id if current else None
        snapshots = list(table.metadata.snapshots)
    except Exception:  # noqa: BLE001 - see the docstring
        return []

    recent = []
    for snapshot in reversed(snapshots[-limit:]):
        rows = snapshot.summary.get("total-records")
        recent.append({
            "at": datetime.fromtimestamp(
                snapshot.timestamp_ms / 1000, tz=UTC,
            ).isoformat(),
            # str() BECAUSE IT IS AN ENUM. Operation.APPEND serialises
            # as an object otherwise, and a panel showing
            # "Operation.APPEND" reads worse than "APPEND".
            "operation": str(snapshot.summary.operation).split(".")[-1],
            "rows": int(rows) if rows is not None else None,
            "current": snapshot.snapshot_id == current_id,
        })
    return recent


class MirrorSnapshot(BaseModel):
    """One point the mirror could be rolled back to."""

    at: str
    operation: str
    rows: int | None
    current: bool


class MirrorTableState(BaseModel):
    silo: str
    table: str
    last_synced_at: str | None
    silver_rows: int | None
    bronze_rows: int | None
    # THE LAST ATTEMPT, as distinct from the last CHANGE. Snapshots
    # record when data changed, so a sync that ran and was refused
    # leaves exactly what a sync that ran and found nothing leaves.
    # One is an incident; the other is Tuesday.
    last_attempt_at: str | None
    last_attempt_outcome: str | None
    last_attempt_detail: str | None
    # WHEN THE DATA CHANGED, newest first. Iceberg records a snapshot
    # per commit and keeps them, so this is history the mirror already
    # holds rather than something new to store.
    #
    # THE NEWEST FEW, NOT ALL OF THEM. A long-running deployment
    # accumulates snapshots -- nothing expires them, which is its own
    # backlog item -- and a panel listing hundreds teaches less than
    # one listing the last handful.
    snapshots: list[MirrorSnapshot] = []


class MirrorStateResponse(BaseModel):
    reading_from_mirror: bool
    tables: list[MirrorTableState]
    problems: list[str]


class TriggerResponse(BaseModel):
    trigger_id: str
    name: str
    view_id: str
    above: int | None
    gained: int | None
    fell: int | None
    enabled: bool
    created_at: str


class TriggersResponse(BaseModel):
    triggers: list[TriggerResponse]


class CreateTriggerRequest(BaseModel):
    name: str
    view_id: str
    above: int | None = None
    gained: int | None = None
    fell: int | None = None


def _trigger_store(request: Request):
    from core.triggers import TriggerStore

    return TriggerStore(
        request.app.state.runtime_paths.data_dir / "triggers.db",
    )


@router.get("/triggers", dependencies=[Depends(_no_store)],
            response_model=TriggersResponse)
def triggers_route(
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """The caller's own triggers.

    NO GRANT REQUIRED. A trigger runs as its owner and notifies only
    its owner, so making one grants nothing somebody did not already
    have -- which is what makes it safe to offer here rather than in
    configuration.
    """
    return {
        "triggers": [
            {
                "trigger_id": trigger.trigger_id,
                "name": trigger.name,
                "view_id": trigger.view_id,
                "above": trigger.above,
                "gained": trigger.gained,
                "fell": trigger.fell,
                "enabled": trigger.enabled,
                "created_at": trigger.created_at,
            }
            for trigger in _trigger_store(request).for_owner(
                current_user.user_id,
            )
        ],
    }


@router.post("/triggers", dependencies=[Depends(_no_store)])
def create_trigger_route(
    body: CreateTriggerRequest,
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Creates one, watching a view the caller owns."""
    thresholds = [body.above, body.gained, body.fell]
    if all(value is None for value in thresholds):
        # A TRIGGER WITH NO CONDITION would evaluate forever and never
        # fire, which reads as broken rather than as quiet.
        raise HTTPException(
            status_code=400,
            detail="A trigger needs one of above, gained or fell.",
        )
    if sum(value is not None for value in thresholds) > 1:
        # ONE QUESTION PER TRIGGER. Two thresholds on one row would
        # need an answer about which wins, and two triggers say it
        # plainly instead.
        raise HTTPException(
            status_code=400,
            detail="A trigger watches one of above, gained or fell, not several.",
        )

    # THE VIEW MUST BE THE CALLER'S OWN, checked by looking in THEIR
    # list rather than by fetching and comparing. `get` takes no owner
    # -- it is the scheduler's call -- so using it here would be the
    # one place this store's scoping could be bypassed.
    owned = {
        view.view_id
        for view in _saved_view_store(request).for_owner(current_user.user_id)
    }
    if body.view_id not in owned:
        raise HTTPException(status_code=404, detail="No such saved view")

    trigger_id = _trigger_store(request).create(
        current_user.user_id, body.name, body.view_id,
        body.above, body.gained, body.fell,
    )
    if trigger_id is None:
        raise HTTPException(status_code=500, detail="Could not create that trigger")
    return {"trigger_id": trigger_id}


@router.post("/triggers/{trigger_id}/enabled", dependencies=[Depends(_no_store)])
def set_trigger_enabled_route(
    trigger_id: str,
    enabled: bool,
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Turns one on or off.

    ENABLED RATHER THAN DELETED is the common case: somebody
    silencing a noisy trigger usually wants it back.
    """
    if not _trigger_store(request).set_enabled(
        current_user.user_id, trigger_id, enabled,
    ):
        raise HTTPException(status_code=404, detail="No such trigger")
    return {"enabled": enabled}


@router.delete("/triggers/{trigger_id}", dependencies=[Depends(_no_store)])
def delete_trigger_route(
    trigger_id: str,
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """A 404 FOR SOMEBODY ELSE'S: the DELETE matches no row."""
    if not _trigger_store(request).delete(current_user.user_id, trigger_id):
        raise HTTPException(status_code=404, detail="No such trigger")
    return {"deleted": True}


class SavedViewResponse(BaseModel):
    view_id: str
    name: str
    object_type: str
    query_text: str
    conditions: list[dict[str, Any]]
    created_at: str


class SavedViewsResponse(BaseModel):
    views: list[SavedViewResponse]


class SaveViewRequest(BaseModel):
    name: str
    object_type: str
    query_text: str = ""
    conditions: list[dict[str, Any]] = []


def _saved_view_store(request: Request):
    from core.saved_views import SavedViewStore

    return SavedViewStore(
        request.app.state.runtime_paths.data_dir / "saved_views.db",
    )


@router.get("/saved-views", dependencies=[Depends(_no_store)],
            response_model=SavedViewsResponse)
def saved_views_route(
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """The caller's own saved views.

    NO GRANT REQUIRED: these are the caller's own searches, and the
    store scopes by owner IN THE QUERY. There is no call that returns
    everybody's.
    """
    return {
        "views": [
            {
                "view_id": view.view_id,
                "name": view.name,
                "object_type": view.object_type,
                "query_text": view.query_text,
                "conditions": view.conditions,
                "created_at": view.created_at,
            }
            for view in _saved_view_store(request).for_owner(
                current_user.user_id,
            )
        ],
    }


@router.post("/saved-views", dependencies=[Depends(_no_store)])
def save_view_route(
    body: SaveViewRequest,
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Saves one, replacing any of the same name.

    THE OBJECT TYPE IS CHECKED AGAINST WHAT THE CALLER MAY SEE. A view
    naming a type they cannot discover would be a view that always
    matches nothing -- and the refusal says so at the moment they can
    fix it.
    """
    visible = _generation(request).mediator.visible_schema(current_user)
    if body.object_type not in visible:
        raise HTTPException(
            status_code=404,
            detail=f"No object type {body.object_type!r}",
        )

    view_id = _saved_view_store(request).save(
        current_user.user_id, body.name, body.object_type,
        body.query_text, body.conditions,
    )
    if view_id is None:
        raise HTTPException(status_code=500, detail="Could not save that view")
    return {"view_id": view_id}


@router.delete("/saved-views/{view_id}", dependencies=[Depends(_no_store)])
def delete_saved_view_route(
    view_id: str,
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Deletes one, if it belongs to the caller.

    A 404 FOR SOMEBODY ELSE'S, not a 403: the DELETE matches no row,
    which is the same answer as "no such view", and telling a caller
    that one exists but is not theirs says more than refusing to say
    anything.
    """
    if not _saved_view_store(request).delete(current_user.user_id, view_id):
        raise HTTPException(status_code=404, detail="No such saved view")
    return {"deleted": True}


class NotificationResponse(BaseModel):
    notification_id: str
    created_at: str
    kind: str
    summary: str
    detail: str | None
    seen: bool


class NotificationsResponse(BaseModel):
    notifications: list[NotificationResponse]
    unseen: int


def _notification_store(request: Request):
    from core.notifications import NotificationStore

    return NotificationStore(
        request.app.state.runtime_paths.data_dir / "notifications.db",
    )


@router.get("/notifications", dependencies=[Depends(_no_store)],
            response_model=NotificationsResponse)
def notifications_route(
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """What is waiting for the caller.

    NO GRANT REQUIRED, because these are the caller's OWN
    notifications and nobody else's. The store scopes by user_id IN
    THE QUERY -- there is no call that returns everyone's, so there is
    no privileged view for a bug to leak from.
    """
    store = _notification_store(request)
    return {
        "notifications": [
            {
                "notification_id": n.notification_id,
                "created_at": n.created_at,
                "kind": n.kind,
                "summary": n.summary,
                "detail": n.detail,
                "seen": n.seen,
            }
            for n in store.for_user(current_user.user_id)
        ],
        "unseen": store.unseen_count(current_user.user_id),
    }


@router.post("/notifications/{notification_id}/seen",
             dependencies=[Depends(_no_store)])
def mark_notification_seen_route(
    notification_id: str,
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Marks one seen, if it belongs to the caller.

    A 404 FOR SOMEBODY ELSE'S, not a 403. Telling a caller that a
    notification exists but is not theirs says more than refusing to
    say anything -- and the store's UPDATE simply matches no row,
    which is the same answer as "no such notification".
    """
    if not _notification_store(request).mark_seen(
        current_user.user_id, notification_id,
    ):
        raise HTTPException(status_code=404, detail="No such notification")
    return {"seen": True}


class SyncStartedResponse(BaseModel):
    started: bool
    detail: str


@router.post("/admin/mirror/sync", dependencies=[Depends(_no_store)],
             response_model=SyncStartedResponse)
def admin_mirror_sync_route(
    request: Request,
    current_user: UserRecord = Depends(get_current_user),
) -> dict:
    """Starts a sync, and returns before it finishes.

    A SYNC IS NOT INSTANT. Two seconds on the shipped fixtures, but
    ROADMAP.md measured 500,000 rows in 2.46s and about a minute for
    ten million. A synchronous request would hold a connection for
    that long, and the one worker process with it.

    SO IT RUNS ON A THREAD and this returns immediately. The SAME
    SHAPE as `install_sighup_handler`, which reloads configuration the
    same way and injects its thread factory for exactly the reason
    this one does.

    **NOTHING NEW REPORTS THE RESULT.** `run_sync()` already records
    every attempt in `sync_attempts.db`, and the mirror panel already
    polls every thirty seconds -- so the outcome arrives through
    machinery that exists, rather than through a job id nobody would
    poll.

    **AND NOTHING NEW GUARDS IT.** `run_sync()` takes an exclusive
    flock for the duration and yields False if another holds it, so a
    second sync cannot start. A button pressed twice does one sync,
    and the second press is told so.

    GATED ON manage:deployment, the same grant that can reload -- and
    a stricter bar than reading the panel, because this one DOES
    something. A sync reads a customer's database and rewrites the
    mirror every user then reads.
    """
    generation = _generation(request)
    if not authorize(current_user, generation.config.roles, "manage:deployment"):
        raise HTTPException(
            status_code=403,
            detail="You need manage:deployment to start a sync.",
        )

    if not generation.config.read_from_mirror:
        # A LIVE DEPLOYMENT HAS NO MIRROR TO FILL. Starting a sync
        # would work and serve nobody, which is worse than refusing.
        raise HTTPException(
            status_code=409,
            detail="This deployment reads live, so there is no mirror to sync.",
        )

    generation.mediator.audit_log.log_access(
        current_user.user_id, "_mirror", "_sync", "start", None, True,
    )

    thread_factory = getattr(request.app.state, "sync_thread_factory",
                             threading.Thread)
    thread_factory(target=_run_sync_in_background, daemon=True).start()

    return {
        "started": True,
        "detail": (
            "A sync is running. Its outcome will appear in this panel's "
            "last-attempt column."
        ),
    }


def _run_sync_in_background() -> None:
    """Runs one sync, swallowing everything.

    A THREAD THAT RAISES TAKES ITS EXCEPTION NOWHERE. Nobody is
    waiting on it, so an escaping error would be lost entirely --
    whereas run_sync() has already recorded what happened in
    sync_attempts.db before any exception could reach here.
    """
    from scripts.run_sync import run_sync

    try:
        run_sync()
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception("a sync started from the mirror panel failed")


@router.get("/admin/mirror", dependencies=[Depends(_no_store)],
            response_model=MirrorStateResponse)
def admin_mirror_route(request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> dict:
    """What the mirror holds, table by table.

    WE BUILT AN INTEGRITY GUARANTEE AND LEFT IT INVISIBLE. A value that
    cannot be coerced fails the whole table's sync, silver keeps its
    previous snapshot, and bronze accepts the bad value so it can be
    diagnosed. Proven, and correct. The only trace is stderr on
    whatever ran the sync -- so a user sees data three days stale and
    an administrator cannot find out why from inside the product.

    That mattered less when the mirror was opt-in. It is now the read
    path.

    BRONZE AND SILVER COUNTS SIDE BY SIDE, because their DIVERGENCE is
    the drift state: bronze took the new rows, silver refused to
    interpret them, and the gap between the two numbers is what a
    refused sync looks like from outside.

    GATED ON manage:deployment, the same grant that can reload. Row
    counts describe the deployment's plumbing rather than its data --
    but a count is still a fact about how much there is, and an
    ordinary user has no reason to see it.

    NO COUNTS FROM THE SOURCE. Answering "how far behind is the
    mirror" would mean reading the customer's database on every page
    load, which is what the mirror exists to avoid.
    """
    generation = _generation(request)
    if not authorize(current_user, generation.config.roles, "manage:deployment"):
        raise HTTPException(
            status_code=403,
            detail="You need manage:deployment to see the mirror's state.",
        )

    if not generation.config.read_from_mirror:
        # NOT AN ERROR. A deployment reading live has no mirror state
        # to report, and saying so is more useful than an empty list
        # that looks like a broken sync.
        return {"reading_from_mirror": False, "tables": [], "problems": []}

    # BUILT HERE RATHER THAN HELD ON THE GENERATION, because this is
    # the only reader of it and a catalog pinned at load would go stale
    # the moment a sync ran -- which is precisely the state this
    # endpoint exists to report.
    mirror_dir = request.app.state.runtime_paths.data_dir / "mirror"
    mirror_dir.mkdir(parents=True, exist_ok=True)
    catalog = SqlCatalog(
        "elysium_mirror",
        uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
        warehouse=f"file://{mirror_dir / 'warehouse'}",
    )
    sync = IcebergMirrorSync(mirror_dir, {})
    attempts = SyncAttempts(mirror_dir / "sync_attempts.db")
    tables = []
    for target in resolve_sync_targets({"object_types": generation.config.schema}):
        synced_at = sync.last_synced_at(target.silo_name, target.table_name)
        attempt = attempts.last_for(target.silo_name, target.table_name)
        tables.append({
            "silo": target.silo_name,
            "table": target.table_name,
            "last_synced_at": synced_at.isoformat() if synced_at else None,
            "silver_rows": _row_count(catalog, f"{target.silo_name}.{target.table_name}"),
            "bronze_rows": _row_count(
                catalog, f"bronze_{target.silo_name}.{target.table_name}",
            ),
            "last_attempt_at": attempt.at.isoformat() if attempt else None,
            "last_attempt_outcome": attempt.outcome if attempt else None,
            "last_attempt_detail": attempt.detail if attempt else None,
            "snapshots": _recent_snapshots(
                catalog, f"{target.silo_name}.{target.table_name}",
            ),
        })

    report = check_mirror(
        catalog, generation.config.schema,
        mirror_dir / "warehouse",
    )
    return {
        "reading_from_mirror": True,
        "tables": tables,
        "problems": list(report.problems),
    }


@router.get("/admin/metrics", dependencies=[Depends(_no_store)],
            response_model=MetricsResponse)
def admin_metrics_route(request: Request, window_seconds: int = 3600,
                         current_user: UserRecord = Depends(get_current_user)) -> dict:
    """Rate, errors and duration over a recent window.

    THE RED METHOD, which is the canonical starting point for a
    request-driven service because a single request-duration record
    yields all three.

    SATURATION IS ABSENT ON PURPOSE. It is the fourth golden signal and
    a property of the HOST -- CPU, memory, queue depth -- so answering
    it from inside the process would mean guessing at limits we do not
    know. It belongs to whatever watches the machine, and a made-up
    number here would be worse than the gap.

    GATED ON manage:deployment, the same grant that can reload. Request
    timings say which routes are used and how often, which is a shape
    of the deployment's activity rather than of its data -- but it is
    still more than an ordinary user should see about everyone else.

    NO-STORE, because a cached metrics response is a lie that looks
    like a measurement.
    """
    generation = _generation(request)
    if not authorize(current_user, generation.config.roles, "manage:deployment"):
        raise HTTPException(status_code=403, detail="Not permitted")

    metrics = request.app.state.request_metrics
    return {
        **metrics.summary(window_seconds),
        "slowest_routes": metrics.slowest_routes(window_seconds),
    }


@router.get("/admin/config-history", response_model=ConfigHistoryResponse)
def config_history_route(request: Request,
                         current_user: UserRecord = Depends(get_current_user)) -> dict:
    """What configurations this deployment has run, most recent first.

    Answers the question a reload otherwise leaves open. The audit log
    records that generation 7 became 8; without this there is no way to
    see what either WAS.

    GATED ON manage:deployment, the same grant that can reload. Someone
    who may replace the configuration may see which ones have run.
    """
    generation = _generation(request)
    if not authorize(current_user, generation.config.roles, "manage:deployment"):
        raise HTTPException(status_code=403, detail="Not authorized to view configuration history")

    history = request.app.state.config_history
    return {
        "current_generation": generation.generation,
        "generations": [
            {"generation": r.generation, "loaded_at": r.loaded_at,
             "source_digest": r.source_digest}
            for r in history.list_generations()
        ],
    }


class ConfigDiffResponse(BaseModel):
    """What changed between two configurations, file by file."""

    older: int
    newer: int
    changed_files: list[str]
    unchanged: bool


@router.get("/admin/config-history/{older}/{newer}", response_model=ConfigDiffResponse)
def config_diff_route(older: int, newer: int, request: Request,
                      current_user: UserRecord = Depends(get_current_user)) -> dict:
    """WHICH FILES differ between two generations, not their contents.

    Naming the changed files is enough to answer "did the policy change
    or only the models?" -- which is the question an operator has at
    three in the morning -- without returning silo hosts and credential
    references over HTTP. Reading the files themselves requires access
    to the machine, which is the correct bar for that.
    """
    generation = _generation(request)
    if not authorize(current_user, generation.config.roles, "manage:deployment"):
        raise HTTPException(status_code=403, detail="Not authorized to view configuration history")

    try:
        changed = request.app.state.config_history.diff(older, newer)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {
        "older": older, "newer": newer,
        "changed_files": sorted(changed),
        # Explicit rather than inferred from an empty list: a reload of
        # UNCHANGED files is a real and common event, and "nothing
        # changed" should not look like "I found nothing".
        "unchanged": not changed,
    }


@router.get("/config", response_model=DeploymentConfigResponse)
def deployment_config_route(request: Request,
                             current_user: UserRecord = Depends(get_current_user)) -> dict:
    """The deployment's own settings, for someone diagnosing behaviour.

    GATED ON manage:users, the same grant Admin uses. Configuration
    discloses deployment shape -- which silos exist, which models run,
    how many object types there are -- and while none of that is
    object DATA, it is the kind of thing an attacker maps a system
    with. An ordinary user has no reason to need it.

    WHAT IS DELIBERATELY ABSENT: llm_connection, silo connection
    details, and the users dict. The first two carry hosts, paths and
    credential references -- exactly the material the Silo work says
    must never reach a UI. The third is already served, properly
    scoped, by /users.

    Silos are named but not described, and roles are named but their
    grants are not listed: the NAMES answer "what is configured", the
    contents would answer "what could I attack".
    """
    _require_manage_users(request, current_user)
    config = _generation(request).config
    return {
        "generation": config.generation,
        "loaded_at": config.loaded_at.isoformat(),
        "source_digest": config.source_digest,
        "llm_provider": config.llm_provider,
        "step_model": config.step_model,
        "synthesis_model": config.synthesis_model,
        "max_hops": config.max_hops,
        "max_consecutive_duplicates": config.max_consecutive_duplicates,
        "max_consecutive_invalid_steps": config.max_consecutive_invalid_steps,
        "max_concurrent_requests": config.max_concurrent_requests,
        "security_attribute": config.security_attribute,
        "read_from_mirror": config.read_from_mirror,
        "enabled_tools": list(config.enabled_tools),
        "silo_names": sorted(config.silo_configs),
        "object_type_count": len(config.schema),
        "action_type_count": len(config.action_types),
        "role_names": sorted(config.roles),
    }


class SiloBackedField(BaseModel):
    object_type: str
    field: str
    # The PHYSICAL column, which need not share the field's name --
    # Customer.risk_score reads a column called score_val. When a query
    # returns something unexpected, "which column is this actually
    # reading" is the question, and today it is answerable only by
    # reading YAML.
    column: str
    table: str
    # The join key, which is not in `fields` at all -- id_field is
    # declared beside `storage`. A wrong one does not return wrong
    # values; it returns NOTHING, or another object's row.
    is_identifier: bool = False


class SiloStatusResponse(BaseModel):
    name: str
    adapter: str
    object_types: list[str]
    fields: list[SiloBackedField]
    reachable: bool
    # The KIND of failure, never the message. See the route.
    failure: str | None = None


class AccessTraceEntry(BaseModel):
    object_type: str
    object_id: str | None = None
    action: str
    rbac_allowed: bool
    mac_allowed: bool | None = None
    timestamp: str


@router.get("/requests/{request_id}/trace", response_model=list[AccessTraceEntry])
def request_trace_route(request_id: str, request: Request,
                         current_user: UserRecord = Depends(get_current_user)) -> list[dict]:
    """What was read while serving one of YOUR requests.

    The trust story for putting an agent over sensitive data: an
    answer arrives and this says what it was built from.

    OWNERSHIP IS ENFORCED IN THE READER, not here. A route-level check
    would be a second place for the rule to live, and the reader is
    what every other caller would go through -- so it is the right
    place for the rule to be true.

    An empty list for someone else's request, rather than a 403: the
    same uniform denial every read path uses, so the response never
    distinguishes "no such request" from "not yours".
    """
    entries = _generation(request).mediator.audit_log.entries_for_request(
        request_id, current_user.user_id,
    )
    return [
        {
            "object_type": entry.get("object_type", ""),
            "object_id": (None if entry.get("object_id") is None
                          else str(entry.get("object_id"))),
            "action": entry.get("action", ""),
            "rbac_allowed": bool(entry.get("rbac_allowed")),
            "mac_allowed": entry.get("mac_allowed"),
            "timestamp": entry.get("timestamp", ""),
        }
        for entry in entries
    ]


class NoteResponse(BaseModel):
    id: str
    text: str
    author: str
    created_at: str


class CreateNoteRequest(BaseModel):
    text: str


def _may_read_object(mediator, user_record, object_type: str, object_id: str) -> bool:
    """Whether this caller can see this object at all.

    COUNTING, not reading. get_object() never raises by contract -- an
    unknown id returns a dict of Nones -- so a try/except around it
    tests for something that cannot happen, and every note would be
    accepted. Found by a test asserting a 404 and getting a 201.

    count_objects applies the same RBAC and MAC the read path does, so
    a zero means absent OR denied without distinguishing them, which is
    exactly the answer both callers want.
    """
    try:
        return mediator.count_objects(
            user_record, object_type,
            [FieldFilter(field=_id_field_for(mediator, object_type),
                         operator="equals", value=object_id)],
        ) > 0
    except Exception:
        # An unknown object type reaches here. Same answer as denial.
        return False


def _id_field_for(mediator, object_type: str) -> str:
    return (mediator.schema.get(object_type, {}) or {}).get("id_field", "id")


def _note_kind(object_type: str, object_id: str) -> str:
    """One artifact kind per OBJECT, not one per note.

    list_for() filters by kind, so encoding the object into the kind
    makes "notes on this customer" a single indexed lookup rather than
    a scan of every note in the deployment.
    """
    return f"note:{object_type}:{object_id}"


@router.get("/objects/{object_type}/{object_id}/notes",
            response_model=list[NoteResponse])
def list_notes_route(object_type: str, object_id: str, request: Request,
                      current_user: UserRecord = Depends(get_current_user)) -> list[dict]:
    """Notes attached to one object.

    AUTHORIZED AS THE OBJECT IS, following the same rule edit_history
    settled: a caller who may read the object may read what has been
    written about it. A note referring to a field they cannot see is
    still a note about an object they can, and inventing a second grant
    would mean two places deciding one question.

    A caller who cannot read the object gets an empty list rather than
    an error -- uniform denial, so the response never distinguishes "no
    notes" from "not allowed".
    """
    mediator = _generation(request).mediator
    if not _may_read_object(mediator, current_user, object_type, object_id):
        return []

    notes = request.app.state.artifact_store.list_for(
        current_user.user_id, current_user.role_name, kind=_note_kind(object_type, object_id),
    )
    return [
        {
            "id": note.artifact_id,
            "text": note.body.get("text", ""),
            "author": note.owner_user_id,
            "created_at": note.created_at,
        }
        for note in notes
    ]


@router.post("/objects/{object_type}/{object_id}/notes", status_code=201,
             response_model=NoteResponse)
def create_note_route(object_type: str, object_id: str, body: CreateNoteRequest,
                       request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> dict:
    """Write a note about an object you can read.

    SHARED WITH THE AUTHOR'S ROLE, not private. A note exists so the
    next person handling this customer knows why the fee was waived --
    a private one helps nobody, which is the whole point of writing it
    down rather than remembering it.

    NO EXPIRY. A judgement about why something was done does not stop
    being true, and an operational note that vanished after ninety days
    would be worse than not having written it.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="A note cannot be empty")

    mediator = _generation(request).mediator
    if not _may_read_object(mediator, current_user, object_type, object_id):
        # Uniform denial: the same 404 whether the object is absent or
        # unreadable, so writing a note cannot be used to probe for
        # objects a caller may not see.
        raise HTTPException(status_code=404, detail="Not found")

    artifact_id = request.app.state.artifact_store.save(
        kind=_note_kind(object_type, object_id),
        title=f"Note on {object_type} {object_id}",
        owner_user_id=current_user.user_id,
        body={"text": body.text},
        shared_role=current_user.role_name,
    )
    saved = request.app.state.artifact_store.get(
        artifact_id, current_user.user_id, current_user.role_name,
    )
    return {
        "id": artifact_id,
        "text": body.text,
        "author": current_user.user_id,
        "created_at": saved.created_at if saved else "",
    }


@router.get("/silos", response_model=list[SiloStatusResponse])
def silos_route(request: Request,
                 current_user: UserRecord = Depends(get_current_user)) -> list[dict]:
    """Which silos are configured, what they back, and whether they answer.

    /health already reports reachability, but it is UNAUTHENTICATED and
    therefore deliberately says nothing about why -- a connection error
    routinely carries a host, a path or a username. This is the
    authenticated counterpart, gated on manage:users like the rest of
    Admin, and it can say more.

    MORE, BUT NOT THE MESSAGE. It reports the exception TYPE --
    FileNotFoundError, OperationalError, PermissionError -- which
    distinguishes "the file is gone" from "the disk is full" from "the
    credentials are wrong" without echoing the path back. That is the
    same line /config draws: names and shapes answer "what is
    configured", contents answer "what could I attack".

    An admin could read the YAML anyway. The point is not that the path
    is secret; it is that a UI which never carries it cannot leak it
    through a screenshot, a bug report, or a browser cache.
    """
    _require_manage_users(request, current_user)
    config = _generation(request).config
    mediator = _generation(request).mediator

    # PRIMARY storage, from silo_for_type.
    types_by_silo: dict[str, list[str]] = {name: [] for name in config.silo_configs}
    for object_type, silo_name in getattr(mediator, "silo_for_type", {}).items():
        types_by_silo.setdefault(silo_name, []).append(object_type)

    # AND additional storage, which silo_for_type does not carry.
    #
    # A multi-datasource field lives in a silo that backs no object
    # type primarily -- risk_sql holds Customer.risk_score and nothing
    # else. Listing only primary storage showed it with no types at
    # all, which reads as "unused" and invites someone to remove a silo
    # a field depends on. Found by looking at the screen.
    for object_type, type_def in config.schema.items():
        for storage in (type_def.get("additional_storage") or {}).values():
            silo_name = storage.get("silo")
            # The membership check is DEFENSIVE and unexercised by the
            # fixtures -- no fixture silo holds both primary and
            # additional storage for one type. A deployment where one
            # does is entirely legal, and it would otherwise list the
            # type twice. See test_api.py for why there is no test.
            if silo_name and object_type not in types_by_silo.setdefault(silo_name, []):
                types_by_silo[silo_name].append(object_type)

    # Which FIELDS each silo backs, and the physical column behind
    # each. Grouping fields under their silo is the encoding that
    # scales: current research puts the limit for distinguishing
    # categories by colour at SIX, so a palette cannot carry this for a
    # deployment with many silos. Adjacency can, at any number.
    fields_by_silo: dict[str, list[dict]] = {}
    for object_type, type_def in config.schema.items():
        primary = (type_def.get("storage") or {})
        extra = (type_def.get("additional_storage") or {})
        for field_name, field_info in (type_def.get("fields") or {}).items():
            if field_info.get("type") == "link":
                continue
            storage_key = field_info.get("storage")
            if storage_key and storage_key in extra:
                silo_name = extra[storage_key].get("silo")
                table = extra[storage_key].get("table", "")
            else:
                silo_name = primary.get("silo")
                table = primary.get("table", "")
            if not silo_name:
                continue
            fields_by_silo.setdefault(silo_name, []).append({
                "object_type": object_type,
                "field": field_name,
                "column": get_field_column(field_info, field_name),
                "table": table,
                "is_identifier": False,
            })

        # The IDENTIFIER, once per storage that holds this type.
        #
        # It is not in `fields` -- id_field sits beside `storage` -- so
        # the loop above never sees it, and the mismatch it can carry
        # matters more than a renamed data column: Customer is keyed on
        # customer_id in primary_sql and on cust_ref in risk_sql.
        id_field = type_def.get("id_field")
        if id_field:
            for storage in [primary, *extra.values()]:
                silo_name = storage.get("silo")
                if not silo_name:
                    continue
                fields_by_silo.setdefault(silo_name, []).append({
                    "object_type": object_type,
                    "field": id_field,
                    "column": storage.get("id_column", id_field),
                    "table": storage.get("table", ""),
                    "is_identifier": True,
                })

    statuses = []
    for silo_name in sorted(config.silo_configs):
        adapter = (getattr(mediator, "adapters", {}) or {}).get(silo_name)
        failure = None
        if adapter is None:
            failure = "NotConfigured"
        else:
            try:
                adapter.health_check()
            except Exception as e:
                failure = type(e).__name__
        statuses.append({
            "name": silo_name,
            "adapter": config.silo_configs[silo_name].get("adapter", "unknown"),
            "object_types": sorted(types_by_silo.get(silo_name, [])),
            "fields": sorted(
                fields_by_silo.get(silo_name, []),
                # Identifier FIRST within each object type. Sorting
                # by name alone scattered it -- account_id before
                # balance, tag_id after label -- so the key you need to
                # check landed in a different place for every type.
                key=lambda f: (f["object_type"], not f["is_identifier"], f["field"]),
            ),
            "reachable": failure is None,
            "failure": failure,
        })
    return statuses


@router.post("/users", status_code=201, response_model=CreateUserResponse)
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
    roles = _generation(request).config.roles
    if not authorize(current_user, roles, "manage:users"):
        raise HTTPException(status_code=403, detail="Not authorized to manage users")


@router.get("/me", dependencies=[Depends(_no_store)], response_model=ProfileResponse)
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


@router.get("/data-freshness", dependencies=[Depends(_no_store)], response_model=DataFreshnessResponse)
def data_freshness_route(request: Request,
                          _current_user: UserRecord = Depends(get_current_user)) -> dict:
    # How current the data a caller is reading actually is -- the
    # user-visible half of the read-only mirror architecture (see
    # ROADMAP.md's own "Real, visible data freshness" point).
    #
    # A SEPARATE route rather than a field on GET /me, deliberately:
    # freshness is a property of the DEPLOYMENT, identical for every
    # caller, and has nothing to do with who someone is. Folding a
    # deployment-wide fact into an identity endpoint would make /me
    # mean two unrelated things.
    #
    # Requires a login (like every route but /login) but no particular
    # grant -- this exposes no business data whatsoever, only whether
    # reads are live and, if not, when the mirror last synced.
    # Gating it behind a permission would mean the people most likely
    # to need it (anyone about to approve a write against possibly
    # stale data) are the least likely to see it.
    config = _generation(request).config
    mediator = _generation(request).mediator

    if not config.read_from_mirror:
        # A live deployment reads the customer's real database on every
        # request, so "freshness" is not a meaningful question -- said
        # explicitly rather than returning a null timestamp a caller
        # would have to interpret.
        return {"source": "live", "last_synced_at": None}

    return {"source": "mirror", "last_synced_at": mediator.mirror_synced_at}


@router.get("/me/visible-apps", dependencies=[Depends(_no_store)], response_model=list[VisibleAppResponse])
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
    roles = _generation(request).config.roles
    return [{"name": app["name"], "path": app["path"]} for app in visible_apps_for(current_user, roles)]


@router.get("/me/visible-schema", dependencies=[Depends(_no_store)],
            response_model=dict[str, VisibleObjectTypeResponse])
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
    mediator = _generation(request).mediator
    return mediator.visible_schema(current_user)


# Hard cap on how many search_object_free_text() matches get expanded
# into full result rows below -- a real, deliberate safety limit, not
# genuine pagination (there is no way to ask for "the next page" of
# results yet). Prevents a broad/empty query on a large table from
# triggering an unbounded number of get_object() calls (each already
# its own N-field loop of get_field() calls -- see DataMediator.
# get_object()'s own docstring), not just an unbounded RESPONSE size.
# Paging, matching Foundry's own model: pageSize + pageToken in, and
# nextPageToken + totalCount back. Their documented default is 1,000
# with the default also acting as the maximum; ours is smaller because
# each result costs a real per-object field read, and a UI table shows
# far fewer than a thousand rows at once anyway.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 500


# Page tokens are OPAQUE, following Foundry's own format: a version
# prefix and a base64 payload ("v1.QnVpbGQgdGhlIEZ1dHVyZTo..."). This
# is about coupling, not secrecy. A bare offset like page_token=3 is
# something a client can construct, guess, or build logic around, and
# every such client breaks the day the encoding changes. A version
# prefix also means the encoding CAN change: a v2 token is
# distinguishable from a v1 one rather than silently misread.
#
# Deliberately NOT signed or encrypted. It carries no secret -- a
# caller already knows their own position in their own result set --
# and signing would imply a tamper guarantee this does not make.
_PAGE_TOKEN_VERSION = "v1"


def _encode_page_token(start: int) -> str:
    payload = base64.urlsafe_b64encode(str(start).encode()).decode().rstrip("=")
    return f"{_PAGE_TOKEN_VERSION}.{payload}"


def _decode_page_token(token: str) -> int | None:
    """The offset a token encodes, or None if it is not one of ours.

    Returns None rather than raising for ANY malformed input --
    wrong version, bad base64, non-numeric payload. Foundry's guidance
    is that a client should treat a token as opaque and pass it back
    unchanged, so a garbled token is a client bug; but failing the
    whole request would turn a display glitch into an error page, and
    restarting at page one is both recoverable and obvious.
    """
    version, _, payload = token.partition(".")
    if version != _PAGE_TOKEN_VERSION or not payload:
        return None
    try:
        padded = payload + "=" * (-len(payload) % 4)
        return int(base64.urlsafe_b64decode(padded).decode())
    except (ValueError, UnicodeDecodeError):
        return None


def _page_bounds(page_size: int | None, page_token: str | None, total: int) -> tuple[int, int]:
    """Resolves a request's paging parameters into (start, size).

    CONSISTENCY, stated because Foundry states it: this is their
    "default" pagination behaviour, which "returns the latest results"
    and "may lead to duplicate entries or missing items as data changes
    between page requests". Their opt-in "snapshot" mode, which
    captures the result set before paging begins, is not implemented --
    see ROADMAP.md. Tokens are short-lived and intended for immediate
    sequential use.

    An oversized page_size is clamped rather than rejected, matching
    Foundry: "Requests for more than the maximum page size will be
    reduced to the maximum."
    """
    size = DEFAULT_PAGE_SIZE if page_size is None else max(1, min(page_size, MAX_PAGE_SIZE))
    start = 0
    if page_token:
        decoded = _decode_page_token(page_token)
        if decoded is not None:
            start = decoded
    if start < 0 or start >= total:
        start = 0
    return start, size


def _sorted_by_field(mediator, user_record, object_type: str, object_ids: list,
                      order_by: str) -> list:
    """Orders ids by a field value, `field` or `field:desc`.

    Foundry's own orderBy syntax, simplified to ONE field: theirs
    accepts a comma-separated list, and multi-field ordering is a real
    but separate piece of work rather than something to half-build
    here.

    An unknown or ungranted field leaves the order untouched rather
    than raising. get_field() already returns None for anything the
    caller cannot read, so an ungranted sort column would otherwise
    order everything by None -- silently scrambling results while
    looking successful. Falling back to the stable id order is both
    honest and more useful.
    """
    field_name, _, direction = order_by.partition(":")
    descending = direction.strip().lower() == "desc"

    visible = mediator.visible_schema(user_record).get(object_type) or {}
    if field_name not in (visible.get("fields") or {}):
        return object_ids

    values = {
        object_id: mediator.get_field(user_record, object_type, object_id, field_name)
        for object_id in object_ids
    }
    # Secondary sort on the id itself, so rows sharing a value keep a
    # deterministic order across pages rather than drifting.
    return sorted(
        object_ids,
        key=lambda object_id: (sort_key(values[object_id]), sort_key(object_id)),
        reverse=descending,
    )


@router.get("/objects/{object_type}/matching-ids",
         response_model=MatchingIdsResponse, response_model_exclude_none=True)
def matching_ids_route(object_type: str, request: Request, q: str = "",
                        conditions: str | None = None,
                        current_user: UserRecord = Depends(get_current_user)) -> dict:
    """Every id the current filter matches, for "select all matching".

    WHY IDS AND NOT A FILTER PASSED ONWARD. Foundry's approvals model
    settles this: "a task is an individual change in Foundry. All tasks
    associated with a request must be approved for the request to be
    invoked." What a reviewer approves is a set of SPECIFIC CHANGES,
    never a rule to be resolved later. Their bulk action types take an
    object reference list for the same reason.

    So the filter is resolved HERE, at the moment of selection, and
    what travels onward is the list it produced. A filter that outlived
    the selection would mean a reviewer approving a count that could
    change before they looked -- overnight, twenty more rows match, and
    an approval of 500 quietly becomes 520.

    CAPPED AT THE SAME CEILING THE WRITE MEDIATOR ENFORCES, and refused
    rather than truncated. Returning the first 1000 of 1500 would hand
    back a selection that silently omits a third of what was asked for,
    and nothing downstream could tell.

    MAC APPLIES AS IT DOES EVERYWHERE: this returns what the CALLER can
    see, so two users selecting "all matching" get different sets from
    the same filter, which is correct.
    """
    mediator = _generation(request).mediator
    try:
        parsed = parse_filters(json.loads(conditions)) if conditions else None
    except (json.JSONDecodeError, TypeError) as e:
        raise HTTPException(status_code=400, detail="conditions must be a JSON list") from e

    try:
        matching_ids = mediator.search_object_free_text(
            current_user, object_type, q, conditions=parsed,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if len(matching_ids) > MAX_BULK_OBJECTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{len(matching_ids)} objects match, and at most {MAX_BULK_OBJECTS} "
                f"can be selected at once. Narrow the filter."
            ),
        )

    return {"object_ids": [str(object_id) for object_id in matching_ids]}


@router.get("/objects/{object_type}/search", response_model=SearchResponse)
def search_objects_route(object_type: str, request: Request, q: str = "",
                          page_size: int | None = None, page_token: str | None = None,
                          order_by: str | None = None,
                          # JSON-encoded conditions, because this is a
                          # GET: the URL is what makes a result set
                          # shareable and bookmarkable, and moving it to
                          # a POST body to avoid encoding would cost
                          # that.
                          conditions: str | None = None,
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
    mediator = _generation(request).mediator
    try:
        parsed = parse_filters(json.loads(conditions)) if conditions else None
    except (json.JSONDecodeError, TypeError) as e:
        raise HTTPException(status_code=400, detail="conditions must be a JSON list") from e

    # ONE CONTEXT FOR THE WHOLE REQUEST, created before the first read
    # so the search and every per-object read that follows share an id.
    # A search returning fifty objects writes fifty-one audit lines,
    # and without this they were fifty-one unrelated facts.
    request_context = RequestContext.new()
    try:
        # THE OUT-PARAMETER IS CREATED HERE because this is the
        # caller that reports it. search_object_free_text returns a
        # list of ids to many call sites; changing that shape to
        # carry one boolean would touch every one for a fact most
        # of them do not want.
        search_outcome = SearchOutcome()
        matching_ids = mediator.search_object_free_text(
            current_user, object_type, q, conditions=parsed,
            context=request_context, outcome=search_outcome,
        )
    except ValueError as e:
        # A bad filter is the caller's mistake, not a server fault. The
        # message is already uniform -- an unreadable field reads the
        # same as an absent one -- so it is safe to pass through.
        raise HTTPException(status_code=400, detail=str(e)) from e
    summary_fields = mediator.free_text_searchable_fields(current_user, object_type)

    # SORTED BEFORE PAGING, always. Pagination is only correct if the
    # order is stable: without it a row can silently appear on two
    # pages or on none. The underlying SELECT has no ORDER BY, and
    # while SQLite happens to return primary-key order today, that is
    # an implementation detail -- verified directly, and not something
    # paging should rest on.
    matching_ids = sorted(matching_ids, key=sort_key)
    if order_by:
        matching_ids = _sorted_by_field(
            mediator, current_user, object_type, matching_ids, order_by
        )

    start, size = _page_bounds(page_size, page_token, len(matching_ids))
    page_ids = matching_ids[start:start + size]
    next_start = start + size

    # STRINGIFIED AT THE BOUNDARY, because every other endpoint already
    # says an id is a string and this one did not.
    #
    # ObjectDetailResponse declares `id: str` and FastAPI coerces it;
    # SearchResponse declares `results: list[dict[str, Any]]`, so the
    # raw value passed straight through. The SAME OBJECT therefore had
    # a string id on one endpoint and an integer on another.
    #
    # WHAT IT BROKE. "Select all N matching" returns ids from
    # /matching-ids, which stringifies. The selection set then held "1"
    # while each checkbox asked has(1) -- so the bar said 64 selected
    # and not one row looked it, with nothing to untick.
    #
    # WHY NOBODY NOTICED: Customer ids are already strings, so every
    # manual check on Customer agreed. Only integer-keyed types --
    # Transaction here -- diverged.
    results = [
        {
            "id": str(object_id),
            "fields": mediator.get_object(
                current_user, object_type, object_id, summary_fields,
                context=request_context,
            ),
        }
        for object_id in page_ids
    ]
    return {
        "results": results,
        "total_matches": len(matching_ids),
        "request_id": request_context.request_id,
        "scan_truncated": search_outcome.scan_truncated,
        # Absent, not empty, when there is no further page -- Foundry's
        # own contract is that "the presence of the nextPageToken field
        # indicates that there are more results."
        "next_page_token": (_encode_page_token(next_start)
                            if next_start < len(matching_ids) else None),
    }


@router.get("/objects/{object_type}/{object_id}", response_model=ObjectDetailResponse)
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
    mediator = _generation(request).mediator
    visible = mediator.visible_schema(current_user)
    type_def = visible.get(object_type)
    if type_def is None:
        # NO request_id HERE, deliberately: this returns before any
        # read happens, so there is no trace to ask for. An id
        # promising an empty trace is worse than no id.
        return {"id": object_id, "fields": {}}

    field_names = list(type_def["fields"].keys())
    # ONE CONTEXT PER REQUEST, so every access decision made while
    # serving it carries the same id. RequestContext and the audit
    # field both already existed -- only the Query route created one,
    # so twelve object-reading call sites wrote UNTRACKED audit lines
    # and "what did this request touch" was unanswerable for all of
    # them.
    request_context = RequestContext.new()
    fields = mediator.get_object(
        current_user, object_type, object_id, field_names,
        context=request_context,
    )
    return {"id": object_id, "fields": fields, "request_id": request_context.request_id}


class ProposeActionRequest(BaseModel):
    parameters: dict = {}


@router.get("/me/visible-action-types", dependencies=[Depends(_no_store)],
            response_model=dict[str, VisibleActionTypeResponse], response_model_exclude_none=True)
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
    write_mediator: WriteMediator = _generation(request).write_mediator
    roles = _generation(request).config.roles
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
    write_mediator: WriteMediator = _generation(request).write_mediator
    try:
        # origin="human": this route IS the person-filled form. The
        # agent reaches propose_action() through AgentLoop instead,
        # and passes "agent" there.
        pending_write = write_mediator.propose_action(
            current_user, action_type_name, body.parameters, origin="human",
        )
    except (ValueError, TypeError, PermissionError) as e:
        logger.warning(f"propose_action_route: {action_type_name!r} rejected for {current_user.user_id!r}: {e}")
        roles = _generation(request).config.roles
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
    if request.app.state.query_rate_limiter.is_rate_limited(current_user.user_id):
        raise HTTPException(status_code=429, detail="Too many queries -- please wait before trying again")
    request.app.state.query_rate_limiter.record_query(current_user.user_id)

    loop: AgentLoop = _generation(request).loop
    synthesis_client = _generation(request).synthesis_client
    executor = request.app.state.executor
    event_loop = asyncio.get_running_loop()

    cancel_event = threading.Event()
    watcher_task = asyncio.create_task(_watch_for_disconnect(request, cancel_event))
    try:
        # ONE context per query, created here and threaded down. Every
        # access decision the agent makes while serving this request
        # carries the id, which is what lets a user be shown what was
        # read on their behalf.
        #
        # Created at the ROUTE rather than inside the loop: the request
        # is the unit of work, and the loop is one thing that happens
        # during it.
        request_context = RequestContext.new()
        # refresh_user lets the loop notice a changed or revoked
        # authority BETWEEN HOPS rather than only at the end. The
        # post-query re-verification below still runs and still
        # matters -- it catches a change during the final hop -- but on
        # this deployment a query can run for minutes, and discovering
        # a revocation only after all of it has executed is a long way
        # from "takes effect".
        #
        # Returns None when the account is gone or disabled, which the
        # loop treats the same as a change.
        user_directory = request.app.state.user_directory

        def refresh_user():
            if user_directory.is_user_disabled(current_user.user_id):
                return None
            return user_directory.get_user_record(current_user.user_id)

        result = await event_loop.run_in_executor(
            executor,
            functools.partial(
                loop.run, current_user, body.query, cancel_event, request_context,
                refresh_user=refresh_user,
            ),
        )
    finally:
        cancel_event.set()
        watcher_task.cancel()

    if result.cancelled:
        _generation(request).mediator.audit_log.log_query_cancelled(
            current_user.user_id, body.query, len(result.gathered)
        )
        raise HTTPException(status_code=499, detail="Client disconnected")

    if result.authority_changed:
        # The loop stopped because the acting user's authority moved
        # underneath it. Same 409 as the post-query check below, and
        # deliberately the same message: from the caller's side these
        # are one situation, differing only in how early it was
        # noticed.
        _generation(request).mediator.audit_log.log_query_cancelled(
            current_user.user_id, body.query, len(result.gathered)
        )
        raise HTTPException(
            status_code=409,
            detail="Your permissions changed while this request was processing -- please try again",
        )

    # THE re-verification -- see module docstring. Applies before
    # EITHER branch below.
    #
    # DISABLED IS CHECKED SEPARATELY, because a record comparison
    # cannot see it. get_user_record() returns the same UserRecord
    # whether or not the account is disabled -- verified directly, not
    # assumed -- so a user disabled mid-request with unchanged MAC and
    # role compares EQUAL here and the answer is served.
    #
    # The per-hop refresh_user() above already checks is_user_disabled,
    # so the exposure was narrow: disabled after the last hop but
    # before synthesis finished. Narrow is not none, and the asymmetry
    # was the tell -- two checks of the same thing disagreeing about
    # what "still authorized" means.
    user_directory = request.app.state.user_directory
    current_record_now = user_directory.get_user_record(current_user.user_id)
    if user_directory.is_user_disabled(current_user.user_id) or current_record_now != current_user:
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
                # Also on the pending-write path: a proposed write is
                # the outcome of reads, and "what did it look at before
                # proposing this" is exactly the question a reviewer
                # has.
                "request_id": request_context.request_id,
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
    return QueryResponse(answer=insight, request_id=request_context.request_id)


@router.post("/writes/{write_id}/confirm", response_model=ConfirmWriteResponse)
async def confirm_write_route(write_id: str, body: ConfirmWriteRequest, request: Request,
                               current_user: UserRecord = Depends(get_current_user)) -> dict:
    store: PendingWriteStore = request.app.state.pending_writes
    def may_confirm(candidate) -> bool:
        # THE GRANT, not ownership. Whoever may EXECUTE an action may
        # decide on a proposal of it -- which is what makes an approvals
        # flow possible at all: owner-equality meant the only person who
        # could confirm a write was the one person a four-eyes rule
        # forbids.
        #
        # This is a real widening for a deployment that declares no
        # criteria: previously only the proposer could confirm, now any
        # holder of the grant can. That is the intended model rather
        # than a side effect, and the OPPOSITE policy is now
        # expressible where it was previously hardcoded -- a criterion
        # of `check: user, field: user_id, operator: equals, value:
        # proposer.user_id` restores owner-only confirmation for a
        # deployment that wants it.
        #
        # MAC and the criteria are NOT checked here. Both are evaluated
        # inside confirm_and_execute() against the objects actually
        # touched, which is where they can see what they are deciding
        # about; duplicating them here would be a second, weaker copy.
        return authorize(
            current_user, _generation(request).config.roles,
            f"execute:{candidate.action_type_name}",
        )

    # RESERVED, NOT CLAIMED, and the difference is a lost write.
    # claim() removed the proposal and handed it back, and the decision
    # could then fail -- a four-eyes rule refusing a self-approval, or
    # a field the ontology no longer declares. The write was already
    # gone, so the colleague entitled to approve it never got the
    # chance and nothing told them it had existed.
    #
    # The reservation is released by the context manager on ANY
    # exception, which is exactly the set of cases where the decision
    # did not happen.
    with store.reserved(write_id, may_confirm) as pending:
        return await _decide_reserved_write(
            request, write_id, pending, body.approved, current_user,
        )


async def _decide_reserved_write(request: Request, write_id: str, pending, approved: bool,
                                 current_user: UserRecord):
    if pending is None:
        # Uniform denial -- wrong user, unknown ID, and expired ID all
        # look identical. See module docstring.
        raise HTTPException(status_code=404, detail="Unknown or expired pending write")

    write_mediator: WriteMediator = _generation(request).write_mediator
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
    # THE APPROVER IS PASSED, which is what lets submission criteria be
    # re-evaluated against the person deciding rather than the person
    # who proposed. A four-eyes rule says nothing at propose time --
    # there is no approver yet -- so evaluating only once is why it
    # could not be enforced at all before.
    #
    # functools.partial rather than more positional arguments: the
    # executor call already has four, and a fifth that silently lands
    # in the wrong slot is the kind of mistake this file has made
    # before.
    # RECORD THE DECISION PER TASK, THEN ASK WHETHER THE REQUEST IS
    # WHOLE.
    #
    # Foundry separates the two: approval is per task, invocation is
    # not -- "all tasks associated with a request must be approved for
    # the request to be invoked". A reviewer approves what they can and
    # the request waits for the rest.
    #
    # ONLY THE TASKS THIS REVIEWER MAY DECIDE. Foundry scopes the
    # action to what the reviewer is eligible for: "approve or reject
    # all tasks in the request THAT YOU ARE ELIGIBLE TO REVIEW".
    #
    # What differs between tasks is the OBJECT. Every task shares the
    # request's action type, so the execute: grant is the same for all
    # of them; MAC is what separates them, and a reviewer in one
    # security partition decides the tasks touching it and leaves the
    # rest for someone who can see them.
    store: PendingWriteStore = request.app.state.pending_writes
    eligible = write_mediator.eligible_task_indexes(
        pending, current_user, _generation(request).config.roles,
    )
    for task_index in sorted(eligible):
        store.record_task_decision(write_id, task_index, current_user.user_id, approved)

    if approved and not store.is_fully_approved(write_id):
        # NOT AN ERROR, AND NOT A REFUSAL EITHER. The request is
        # waiting for reviewers who have not decided yet, which is the
        # normal state of a multi-reviewer request rather than a fault.
        #
        # REACHABLE NOW that eligibility exists. A reviewer who can see
        # only part of a request approves their part and gets told the
        # rest is still waiting, rather than a success that did not
        # happen or an error that misdescribes an ordinary state.
        undecided = len(pending.sub_writes) - sum(
            1 for decision in store.task_decisions(write_id).values() if decision.approved
        )
        return {
            "status": "awaiting_other_reviewers",
            "write_id": write_id,
            "tasks_outstanding": undecided,
        }

    try:
        outcome = await event_loop.run_in_executor(
            executor,
            functools.partial(
                write_mediator.confirm_and_execute, pending, approved,
                approver=current_user,
            ),
        )
    except (SubmissionCriteriaViolation, ValueError) as e:
        # A REFUSAL IS A 409, NOT A 500, and the message is the point.
        # These are decisions the system made for a stated reason -- a
        # four-eyes rule declining a self-approval, a field the
        # ontology no longer declares -- and the reviewer needs the
        # reason, not a generic failure.
        #
        # Raising HTTPException here also leaves the reservation
        # released: the context manager releases on ANY exception, and
        # an HTTPException is one. The write goes back in the queue for
        # somebody who can approve it.
        raise HTTPException(status_code=409, detail=str(e)) from e

    return outcome if outcome is not None else {"status": "rejected"}

# --- Object Set operations: the analytical half of the read surface.
# Foundry's own Object Set Service serves "searching, filtering,
# aggregating, and loading"; Elysium had the first two exposed over
# HTTP and neither of the last, so count/aggregate/search-around were
# reachable in DataMediator but not from any UI.
#
# POST rather than GET for all three, deliberately: each takes a
# structured criteria object, and encoding nested JSON into query
# parameters would be both uglier and length-limited. These are reads
# with no side effects despite the verb -- the same trade every
# search-with-a-body API makes.


@router.post("/objects/{object_type}/count", response_model=CountResponse)
def count_objects_route(object_type: str, body: ObjectSetQueryRequest, request: Request,
                         current_user: UserRecord = Depends(get_current_user)) -> dict:
    # The count is of objects THIS CALLER can see, never the raw row
    # count -- two users legitimately get different answers, and a
    # count ignoring MAC would leak the existence of rows outside the
    # caller's boundary.
    mediator = _generation(request).mediator
    try:
        return {"count": mediator.count_objects(current_user, object_type, body.as_conditions())}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/objects/{object_type}/aggregate", response_model=AggregateResponse)
def aggregate_objects_route(object_type: str, body: AggregateRequest, request: Request,
                             current_user: UserRecord = Depends(get_current_user)) -> dict:
    mediator = _generation(request).mediator
    try:
        results = mediator.aggregate_by_field(
            current_user, object_type, body.as_conditions(),
            group_by=body.group_by, aggregate=body.aggregate, field_name=body.field,
        )
    except ValueError as e:
        # An unknown aggregate name or a missing field is a caller
        # mistake, not a server fault.
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Group values become strings for JSON object keys. None -- meaning
    # "no grouping requested" -- becomes "" rather than being dropped.
    return {"results": {("" if group is None else str(group)): metric
                        for group, metric in results.items()}}


@router.post("/objects/{object_type}/search-around", response_model=SearchAroundResponse)
def search_around_route(object_type: str, body: SearchAroundRequest, request: Request,
                         current_user: UserRecord = Depends(get_current_user)) -> dict:
    # MAC applies on BOTH sides: the caller only traverses from objects
    # they can see, and every returned id is authorized individually.
    # An ungranted or non-link field yields an empty list rather than
    # an error -- the same uniform denial every other read path uses,
    # so a caller learns nothing about whether the field exists.
    mediator = _generation(request).mediator
    search_outcome = SearchOutcome()
    ids = mediator.search_around(
        current_user, object_type, body.as_conditions(), body.link_field,
        outcome=search_outcome,
    )
    return {
        "ids": ids,
        "total": len(ids),
        "scan_truncated": search_outcome.scan_truncated,
    }


@router.get("/objects/{object_type}/{object_id}/link-counts",
            response_model=LinkCountsResponse)
def link_counts_route(object_type: str, object_id: str, request: Request,
                       current_user: UserRecord = Depends(get_current_user)) -> dict:
    """How many objects each link leads to, before following any.

    COUNTS BEFORE EXPANSION is the whole design of the link explorer: a
    person deciding whether to follow a link needs to know it leads to
    four things or four thousand BEFORE they commit. Fan-out should
    never be a surprise.

    Every count is what THIS caller would actually receive -- MAC and
    RBAC apply on the far side -- so it cannot disagree with the
    expansion that follows, and cannot leak the size of data they are
    not permitted to see.

    A GET, because it is a question rather than a change, and a person
    sharing a link explorer view should be able to share this too.
    """
    mediator = _generation(request).mediator
    return {"links": mediator.link_counts(current_user, object_type, object_id)}

@router.get("/objects/{object_type}/{object_id}/history", response_model=EditHistoryResponse)
def object_history_route(object_type: str, object_id: str, request: Request,
                          page_size: int | None = None, page_token: str | None = None,
                          current_user: UserRecord = Depends(get_current_user)) -> dict:
    # Foundry's Edit History widget, answering "what changed, by whom,
    # and when?" over the write log this project already keeps.
    #
    # Authorization is the SAME check as reading the object, following
    # Foundry directly: "Users who have access to the current state of
    # an object can access the entire history of the object." A caller
    # who cannot read it gets an empty list rather than an error --
    # uniform denial, so the response never distinguishes "no history"
    # from "not allowed" from "no such object".
    #
    # Paged with the same machinery as search, rather than a second
    # scheme: an object with a long edit history is exactly what a
    # timeline widget scrolls through.
    mediator = _generation(request).mediator

    # Bounds resolved against the COUNT, then only that page is read --
    # rather than reading the whole history and slicing it in Python,
    # which wasted exactly the work paging exists to avoid.
    _empty, total = mediator.edit_history(current_user, object_type, object_id, limit=0)
    start, size = _page_bounds(page_size, page_token, total)
    page, _total = mediator.edit_history(
        current_user, object_type, object_id, limit=size, offset=start
    )
    next_start = start + size
    return {
        "entries": page,
        "total": total,
        "next_page_token": (_encode_page_token(next_start)
                            if next_start < total else None),
    }

@router.get("/health", response_model=HealthResponse)
def health_route(request: Request) -> dict:
    """Whether this service is up and its dependencies are reachable.

    UNAUTHENTICATED, deliberately. A health check that requires a
    session cannot be used by the thing that most needs it -- a load
    balancer, a container orchestrator, or an engineer establishing
    whether the process is even running. It therefore reports only
    whether subsystems ANSWER, never what they contain: no counts, no
    names, no configuration. "reachable" or "unreachable", nothing
    more.

    Returns 200 even when degraded, with the detail in the body. A
    caller distinguishing "the service is down" from "the service is up
    but its database is not" needs both answers to arrive, and a
    non-200 collapses them into one.
    """
    checks: dict[str, str] = {}

    # Through the PIN, not app.state -- which no longer has a mediator
    # at all (step 2e). The getattr default this replaced was written
    # to tolerate a not-yet-wired app, and after the attribute was
    # deleted it silently returned None and reported "unconfigured" on
    # a perfectly healthy deployment. A defensive default outliving the
    # thing it defended against is worse than no default: it turns a
    # missing dependency into a plausible-looking answer.
    mediator = getattr(_generation(request), "mediator", None)
    checks["ontology"] = "ready" if mediator is not None else "unconfigured"

    # SILOS ARE REPORTED IN AGGREGATE, not by name. Each entry was
    # previously keyed "silo:{silo_name}", so an UNAUTHENTICATED caller
    # learned every data source's name and how many there were.
    #
    # The docstring already promised "no counts, names, paths or
    # configuration", and the test enforcing it checked the VALUES and
    # grepped for paths and passwords -- never the KEYS, which is where
    # the names were.
    #
    # A silo name is deployment-chosen and usually descriptive:
    # `risk_sql`, `hr_payroll`, `claims`. On an anonymous endpoint that
    # is reconnaissance, saying what a deployment holds before anyone
    # has logged in.
    #
    # One entry still answers what this endpoint is FOR. A connection
    # indicator needs to know the deployment is degraded, not which
    # part; anyone entitled to the detail has GET /silos, which is
    # authenticated and already backs the Silos screen.
    unreachable = 0
    adapters = getattr(mediator, "adapters", {}) or {}
    for adapter in adapters.values():
        try:
            adapter.health_check()
        except Exception:
            # The reason is deliberately NOT reported. This endpoint is
            # unauthenticated, and a connection error routinely carries
            # a host, a path, or a username.
            unreachable += 1

    if adapters:
        checks["silos"] = "unreachable" if unreachable else "reachable"

    degraded = any(value == "unreachable" for value in checks.values())
    return {"status": "degraded" if degraded else "ok", "checks": checks}

