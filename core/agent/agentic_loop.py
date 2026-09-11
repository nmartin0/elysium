"""
agentic_loop.py  (the agentic loop -- org-agnostic)

AgentLoop bundles everything that stays FIXED across every query for a
given deployment -- the LLMAdapter, the DataMediator, and the hop/
retry limits -- into one object, constructed once. Only run() takes the
truly per-call arguments (user_record, query_text). This used to be a
single function re-passed all seven of these on every call; per-call
that's the same "same parameters, many calls" pattern that means a
class fits better than a function.

Repeatedly asks core/llm/agent_step_prompt.py for the next step
(search_object, get_field, get_object, or finish), executes it against
the DataMediator, and accumulates results until the model signals
"finish", asks for something it already has (duplicate detection), asks
for something invalid (invalid-step recovery), proposes a write, is
cancelled, or max_hops is reached.

WRITES ARE PROPOSE-ONLY, NEVER CONFIRMED HERE: run() used to take a
confirm_write callback and both propose AND execute a write within one
call -- that assumed something HTTP callers can't provide, a
synchronous pause for a human decision mid-request. A proposed write
now STOPS the loop immediately and is returned via AgentLoopResult.
pending_write; confirming it (or not) is always the CALLER's job,
done separately, at whatever time makes sense for that caller (a
terminal prompt for scripts/run_deployment.py; a completely separate
HTTP request for api/). This also means a second write proposal in the
same run() can genuinely never happen -- the first one always stops
the loop -- which is why _step_signature() has no propose_action
deduplication logic; that branch would be unreachable dead code.

CANCELLATION: an optional cancel_event (threading.Event) is checked
once at the TOP of each hop, never mid-hop -- this is about skipping
FURTHER hops after a caller has decided to give up (e.g. api/'s /query
detecting the client disconnected), not about aborting a single
already-in-flight LLM call. AgentLoopResult.cancelled tells the caller
this happened, so it can log the fact rather than silently discard
partial work with no trace.

DUPLICATE DETECTION: small models don't always reliably notice they
already have what they're asking for again, even when told to check.
Rather than depend entirely on the model getting that right, this loop
tracks a signature of every executed step; if the model's next choice
exactly matches one already done, that's treated as an implicit "out of
new ideas" signal and the loop stops -- a mechanical backstop, not just
an instruction.

COMPLETENESS CHECK: similar idea, applied to finishing too early. When
the model tries to finish, this checks whether sibling objects of the
same type have uneven data gathered about them. If so, it gets ONE
corrective nudge before being allowed to finish for real -- soft, not a
hard rule, since some asymmetry is legitimate if a question only needs
certain fields for certain items.

INVALID STEP RECOVERY: same recoverable-mistake philosophy applied to
schema validation errors (e.g. requesting a field that doesn't exist).
The model sees exactly what was invalid and gets a capped number of
retries before the loop actually gives up, rather than discarding
everything gathered so far on the first mistake.

Used by: scripts/run_deployment.py, api/routes.py, and directly by
         tests/integration/
"""

import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.concurrency import ConcurrencyLimiter
from core.deployment_loader import build_llm_adapter
from core.filters import as_equality_conditions
from core.functions.interface import Function
from core.functions.ontology_access import OntologyAccess
from core.functions.registry import get_enabled_functions
from core.intermediate_layer.auth import UserRecord, authorize
from core.llm.agent_step_prompt import next_step
from core.llm.interface import LLMAdapter
from core.ontology.mediator import DataMediator
from core.ontology.submission_criteria import SubmissionCriteriaViolation
from core.ontology.write_mediator import PendingWrite, WriteMediator
from core.request_context import RequestContext

logger = logging.getLogger(__name__)

# The most objects one get_object step may name. A cap exists because
# max_hops bounds how much a single query can read, and an uncapped
# list of ids would let one hop read arbitrarily much -- the same
# reasoning as MAX_SUB_WRITES in core/ontology/action_types.py, which
# cites Palantir capping their own batched action calls.
#
# 20, matching MAX_SUB_WRITES rather than being picked independently:
# both answer "how much may one step do", and two different answers to
# one question is a thing to remember rather than derive. Exceeding it
# is a NAMED error the model can recover from, never a silent short
# read -- Palantir errors with ObjectsExceededLimit for the same
# reason.
MAX_OBJECT_IDS = 20


@dataclass
class AgentLoopResult:
    gathered: list[dict]
    pending_write: PendingWrite | None = None
    cancelled: bool = False
    hit_max_hops: bool = False
    # The acting user's authority changed mid-query and the loop
    # stopped. Distinct from cancelled: nobody asked for this, and the
    # caller should say something different about it.
    authority_changed: bool = False


def _object_ids_in(step: dict) -> list:
    """The objects a get_object step names, whichever key it used.

    Module-level, and used by _step_signature(), the duplicate-
    recording loop in run(), AND AgentLoop._step_get_object(), because
    the first version of the set-shaped read had each of those reading
    step["object_id"] directly. Two of them were missed, and run()
    crashed with a KeyError on the first real query -- caught by a live
    run, not by the tests, which exercised the step handler and the
    parser but never the path between them.
    """
    if "object_ids" in step:
        return list(step["object_ids"])
    return [step["object_id"]]


def _step_signature(step: dict):
    # A hashable fingerprint of one step, used to detect exact repeats.
    # propose_action has NO entry here -- see module docstring for why a
    # second proposal in one run() is now structurally impossible, not
    # just discouraged.
    if step["step"] == "search_object":
        return ("search_object", step["object_type"], frozenset(step["filter"].items()))
    if step["step"] == "get_field":
        return ("get_field", step["object_type"], step["object_id"], step["field_name"])
    if step["step"] == "get_object":
        # frozenset over field_names -- the model asking for the SAME
        # set of fields on the SAME object twice must be detected as a
        # genuine repeat regardless of what ORDER it happened to list
        # them in either time.
        # frozenset over the ids too, for the same reason: naming the
        # same objects in a different ORDER is the same request.
        return ("get_object", step["object_type"], frozenset(_object_ids_in(step)),
                frozenset(step["field_names"]))
    if step["step"] == "use_tool":
        # Function args can contain UNHASHABLE values (e.g. lists for
        # x_values/y_values) -- frozenset(dict.items()), used for the
        # other step types, would crash on these. JSON serialization
        # (sort_keys=True for determinism) handles nested lists/dicts
        # safely and still produces a stable, hashable signature.
        return ("use_tool", step["tool_name"], json.dumps(step["args"], sort_keys=True))
    # Set-based steps are deterministic for the same inputs, so
    # repeating one wastes a step exactly as a repeated get_field does
    # -- worth catching by the same duplicate detection.
    if step["step"] == "aggregate_object":
        return ("aggregate_object", step["object_type"],
                frozenset((step.get("filter") or {}).items()),
                step["aggregate"], step.get("field_name"), step.get("group_by"))
    if step["step"] == "search_around":
        return ("search_around", step["object_type"],
                frozenset((step.get("filter") or {}).items()), step["link_field"])
    return None


def _detect_asymmetry(gathered: list[dict]) -> str | None:
    # Looks for uneven data gathered across sibling objects of the same
    # type (e.g. two transactions where one has 3 fields fetched and the
    # other has 1). Returns a description if found, else None. Ignores
    # link results (a LIST of IDs isn't a data field to compare).
    fields_by_type_id: dict = {}
    for item in gathered:
        if item.get("step") != "get_field":
            continue
        result = item.get("result")
        if isinstance(result, list):
            continue
        object_type = item["object_type"]
        object_id = item["object_id"]
        fields_by_type_id.setdefault(object_type, {}).setdefault(object_id, set()).add(item["field_name"])

    for object_type, id_map in fields_by_type_id.items():
        if len(id_map) < 2:
            continue
        field_sets = [frozenset(f) for f in id_map.values()]
        if len(set(field_sets)) > 1:
            details = ", ".join(f"{oid}: {sorted(fields)}" for oid, fields in id_map.items())
            return f"Uneven data gathered across {object_type} objects -- {details}."
    return None


def _handle_recoverable_mistake(gathered: list[dict], count: int, cap: int, detail: str,
                                 rejected_step_name: str, attempt_label: str,
                                 stop_message: str, note: str) -> tuple[int, bool]:
    # Shared logic for BOTH duplicate-step and invalid-step recovery: log
    # progress toward the cap, and either inject a corrective bookkeeping
    # note (giving the model another chance) or signal the caller to stop
    # if the cap is hit. Returns (new_count, should_stop) -- the caller
    # does the actual break, since a function can't break its caller's
    # loop directly.
    count += 1
    logger.warning(f"{attempt_label} ({count}/{cap}): {detail}")

    if count >= cap:
        logger.warning(stop_message)
        return count, True

    gathered.append({"step": rejected_step_name, "note": note})
    return count, False


class _StepHandled:
    """A handler that has already recorded whatever it needed to.

    A sentinel rather than None, because None is a legitimate RESULT --
    get_field on a field that is null returns it, and `gathered` should
    record that rather than silently drop the step.
    """

    def __repr__(self) -> str:
        return "STEP_HANDLED"


STEP_HANDLED = _StepHandled()


@dataclass(frozen=True)
class _ProposalPending:
    """A write awaiting a human. The one thing that stops the loop."""

    pending: PendingWrite


class AgentLoop:
    # Step types that are process bookkeeping, not real gathered data --
    # filter_real_data() strips these before handing results to synthesis.
    BOOKKEEPING_STEPS = frozenset({
        "rejected_duplicate", "completeness_check", "rejected_invalid_step", "rejected_business_rule",
    })

    def __init__(self, client: LLMAdapter, mediator: DataMediator, tools: list[Function] | None = None,
                 write_mediator: WriteMediator | None = None,
                 max_hops: int = 8, max_consecutive_duplicates: int = 2,
                 max_consecutive_invalid_steps: int = 2):
        # These stay fixed across every query this loop instance ever
        # runs -- constructed once per deployment, then run() called
        # once per actual user question. tools defaults to None, not []
        # -- the classic Python mutable-default-argument trap.
        #
        # write_mediator defaults to None -- writes are OPT-IN, unlike
        # data/LLM/tools which every deployment needs. None means this
        # loop simply never proposes writes (see agent_step_prompt.py's
        # writes_enabled flag). Confirming/executing a proposed write
        # is NEVER this class's job -- see module docstring.
        self.client = client
        self.mediator = mediator
        self.tools = tools if tools is not None else []
        self._tools_by_name = {tool.name: tool for tool in self.tools}
        self._tool_limiters = {
            tool.name: ConcurrencyLimiter(tool.max_concurrent_calls) for tool in self.tools
        }
        self.write_mediator = write_mediator
        self.max_hops = max_hops
        self.max_consecutive_duplicates = max_consecutive_duplicates
        self.max_consecutive_invalid_steps = max_consecutive_invalid_steps

    @classmethod
    def from_deployment(cls, deployment, mediator: DataMediator,
                         write_mediator: WriteMediator | None = None) -> "AgentLoop":
        # The standard way every caller should build an AgentLoop -- one
        # authoritative place reading deployment.max_hops etc. write_mediator
        # is NOT built here automatically (unlike tools) -- a caller not
        # passing one gets a loop with writes fully disabled, the correct
        # default.
        client = build_llm_adapter(deployment, deployment.step_model)
        tools = get_enabled_functions(deployment.enabled_tools)
        return cls(
            client, mediator, tools=tools,
            write_mediator=write_mediator,
            max_hops=deployment.max_hops,
            max_consecutive_duplicates=deployment.max_consecutive_duplicates,
            max_consecutive_invalid_steps=deployment.max_consecutive_invalid_steps,
        )

    @staticmethod
    def filter_real_data(gathered: list[dict]) -> list[dict]:
        # Strips process bookkeeping entries AND denied/empty field
        # reads -- what's LEFT is what should actually be handed to
        # synthesis.
        #
        # A get_field() call denied by RBAC/MAC returns None -- same
        # value as a field that's genuinely NULL in the database,
        # DELIBERATELY indistinguishable (see core/ontology/mediator.py's
        # docstring on uniform denial). Without this filter, that literal
        # None would still reach the synthesis prompt as a real gathered
        # item, relying ENTIRELY on the model correctly interpreting it
        # as "omit this" -- pure trust in model behavior, the one thing
        # this project has been careful never to rely on anywhere else.
        # Stripping it here means a denied field is structurally ABSENT
        # from what the model sees, identical to never having asked at
        # all -- nothing left for the model to be tempted to fill in.
        #
        # search_object() results are always lists (possibly empty),
        # never bare None -- this only ever actually filters get_field
        # (and, defensively, a tool call that happened to return None).
        return [
            item for item in gathered
            if item["step"] not in AgentLoop.BOOKKEEPING_STEPS and item.get("result") is not None
        ]

    def _handle_finish_attempt(self, gathered: list[dict], asymmetry_nudged: bool) -> tuple[bool, bool]:
        # Called when the model wants to finish. Gives ONE corrective
        # nudge if sibling objects have uneven data gathered (see
        # _detect_asymmetry), otherwise allows the finish to go through.
        # Returns (should_stop_loop, new_asymmetry_nudged_value).
        if asymmetry_nudged:
            return True, asymmetry_nudged

        asymmetry = _detect_asymmetry(gathered)
        if not asymmetry:
            return True, asymmetry_nudged

        logger.warning(f"asymmetry detected at finish, one nudge: {asymmetry}")
        gathered.append({
            "step": "completeness_check",
            "note": f"{asymmetry} If this gap matters for the "
                    f"question, fill it in; otherwise finish is fine.",
        })
        return False, True

    # --- Step handlers --------------------------------------------------
    #
    # One method per step kind, and a table mapping names to them.
    #
    # This was a seven-branch if/elif chain with cyclomatic complexity
    # 21. The branches were never the problem individually -- most are
    # a single mediator call -- but they sat inside shared try/except
    # handling, so reading any one of them meant reading all of them,
    # and adding a step kind meant editing a function that already did
    # seven things.
    #
    # A handler returns either a RESULT to append to `gathered`, or the
    # STEP_HANDLED sentinel when it has already appended (or has
    # nothing to append). Three kinds need that: get_object fans one
    # step out into several gathered entries, an auto-executed action
    # records its own, and a proposed action stops the loop instead.

    def _step_search_object(self, step: dict, user_record: UserRecord,
                            visible_schema: dict, gathered: list[dict],
                            context: RequestContext | None = None) -> Any:
        return self.mediator.search_object(
            user_record, step["object_type"],
            as_equality_conditions(step["filter"]),
            visible_schema=visible_schema,
            context=context,
        )

    def _step_get_field(self, step: dict, user_record: UserRecord,
                        visible_schema: dict, gathered: list[dict],
                        context: RequestContext | None = None) -> Any:
        return self.mediator.get_field(
            user_record, step["object_type"], step["object_id"], step["field_name"],
            context=context,
        )

    def _step_aggregate_object(self, step: dict, user_record: UserRecord,
                               visible_schema: dict, gathered: list[dict],
                               context: RequestContext | None = None) -> Any:
        return self.mediator.aggregate_by_field(
            user_record, step["object_type"], as_equality_conditions(step.get("filter") or {}),
            group_by=step.get("group_by"),
            aggregate=step["aggregate"],
            field_name=step.get("field_name"),
        )

    def _step_search_around(self, step: dict, user_record: UserRecord,
                            visible_schema: dict, gathered: list[dict],
                            context: RequestContext | None = None) -> Any:
        return self.mediator.search_around(
            user_record, step["object_type"], as_equality_conditions(step.get("filter") or {}),
            step["link_field"],
            context=context,
        )

    def _step_get_object(self, step: dict, user_record: UserRecord,
                         visible_schema: dict, gathered: list[dict],
                         context: RequestContext | None = None) -> Any:
        """Fans ONE step out into one gathered entry per object per field.

        SET-SHAPED ON BOTH AXES. `field_names` was always a list;
        `object_ids` now is too. This is the N+1 problem in an agentic
        loop: a search returns a list of ids, and reading one field
        from each of them used to cost one HOP per id. On the CPU-only
        deployment this was written for a hop was measured at ~193
        seconds, so two transactions cost 6.4 minutes to read one field
        each.

        The usual fix -- DataLoader, collecting individual loads and
        issuing one bulk query underneath -- does not apply here. It
        works because the caller's loads happen within one tick and can
        be batched invisibly. Our caller is a model that must emit each
        read as a separate, expensive round trip; there is no tick to
        batch within. So the vocabulary has to change, which is what
        REST does when transparent batching is impossible.

        Shaped after Palantir's ObjectSet rather than as a batch
        variant of a singular verb: their read primitive takes a SET
        plus a `select` of which properties to return, and a
        single-object fetch is the special case. `object_id` (singular)
        still works and is normalised to a one-element list, so nothing
        that already worked stops working.

        Recorded as get_field entries so everything downstream --
        synthesis, the trace, the prompt's own history -- sees the same
        shape whether a field was fetched singly or in a batch.

        NOTHING ABOUT AUTHORIZATION IS BATCHED, and that is worth
        stating because "batch read" invites the opposite assumption.
        mediator.get_object() remains a per-field loop around
        get_field(), and this adds a per-object loop around that: every
        RBAC grant, every MAC check and every audit entry still happens
        once per field per object, exactly as if the model had asked
        one at a time. The saving is round trips to the MODEL, not work
        in the mediator.

        Relatedly, and deliberately not done: DataLoader's other half
        is a per-request cache keyed by id. Adding one here would be a
        second place authorization state could go stale, and the
        pattern's own guidance is that such caches must be per-request
        precisely to prevent leakage between users. Not worth it for a
        loop that reads a handful of objects.
        """
        object_ids = self._object_ids_for(step)
        for object_id in object_ids:
            field_values = self.mediator.get_object(
                user_record, step["object_type"], object_id, step["field_names"]
            )
            for field_name, value in field_values.items():
                gathered.append({
                    "step": "get_field", "object_type": step["object_type"],
                    "object_id": object_id, "field_name": field_name, "result": value,
                })
        return STEP_HANDLED

    @staticmethod
    def _object_ids_for(step: dict) -> list:
        # Accepts either key. A step naming one `object_id` is the
        # common case and keeps working unchanged.
        if "object_ids" in step and (
                not isinstance(step["object_ids"], list) or not step["object_ids"]):
            raise ValueError("get_object: 'object_ids' must be a non-empty list")
        object_ids = _object_ids_in(step)

        if len(object_ids) > MAX_OBJECT_IDS:
            # A NAMED refusal, never a silent truncation -- answering
            # about some of a list and quietly skipping the rest is the
            # exact failure the prompt already warns the model against.
            # Palantir does the same at their own scale, erroring with
            # ObjectsExceededLimit rather than returning a short page.
            #
            # A cap exists at all because max_hops bounds how much a
            # query can read, and an uncapped list would let one hop
            # read arbitrarily much. Same reasoning as MAX_SUB_WRITES
            # in core/ontology/action_types.py.
            raise ValueError(
                f"get_object: {len(object_ids)} object_ids exceeds the "
                f"limit of {MAX_OBJECT_IDS}. Ask for fewer at a time."
            )
        return object_ids

    def _step_use_tool(self, step: dict, user_record: UserRecord,
                       visible_schema: dict, gathered: list[dict],
                       context: RequestContext | None = None) -> Any:
        tool = self._tools_by_name.get(step["tool_name"])
        tool_name = step["tool_name"]
        if tool is None:
            raise ValueError(f"Unknown tool: {tool_name!r}")
        action = f"tool:{tool_name}"
        rbac_allowed = authorize(user_record, self.mediator.roles, action)
        self.mediator.audit_log.log_access(
            user_record.user_id, "tool", tool_name, action, mac_allowed=True,
            rbac_allowed=rbac_allowed,
        )
        # SAME message as an unknown tool, deliberately: a caller must
        # not learn that a tool EXISTS by being refused it.
        if not rbac_allowed:
            raise ValueError(f"Unknown tool: {tool_name!r}")
        call_args = dict(step["args"])
        declared = getattr(tool, "reads_object_types", []) or []
        if declared:
            call_args["ontology"] = OntologyAccess(self.mediator, user_record, declared)
        with self._tool_limiters[tool.name].limit():
            return tool.run(**call_args)

    def _step_propose_action(self, step: dict, user_record: UserRecord,
                             visible_schema: dict, gathered: list[dict],
                             context: RequestContext | None = None) -> Any:
        if self.write_mediator is None:
            raise ValueError("Writes are not enabled for this deployment")
        # origin="agent": user_record is still the person whose
        # permissions authorize this, but the LLM chose the action,
        # not them. Recording only user_id would make this
        # indistinguishable from a form they filled in themselves.
        pending = self.write_mediator.propose_action(
            user_record, step["action_type"], step["parameters"], origin="agent",
        )
        action_def = self.write_mediator.action_types.get(step["action_type"]) or {}
        if action_def.get("auto_execute") is True:
            self.write_mediator.confirm_and_execute(pending, approved=True)
            result = {"status": "auto_executed", "action_type": step["action_type"]}
            gathered.append({"step": step, "result": result})
            return STEP_HANDLED
        # The only handler that stops the loop: a proposal needs a
        # human before anything else happens.
        return _ProposalPending(pending)

    def _step_handlers(self) -> dict:
        return {
            "search_object": self._step_search_object,
            "get_field": self._step_get_field,
            "aggregate_object": self._step_aggregate_object,
            "search_around": self._step_search_around,
            "get_object": self._step_get_object,
            "use_tool": self._step_use_tool,
            "propose_action": self._step_propose_action,
        }

    def _execute_step(self, step: dict, user_record: UserRecord, visible_schema: dict,
                       gathered: list[dict], consecutive_invalid: int, consecutive_business_rule: int,
                       context: RequestContext | None = None
                       ) -> tuple[int, int, bool, PendingWrite | None]:
        """Runs one step, counting mistakes and deciding whether to stop.

        The dispatch is a table; what remains here is what is genuinely
        SHARED -- the two recoverable-mistake handlers, and the
        bookkeeping every step kind reports back through.
        """
        handler = self._step_handlers().get(step["step"])
        if handler is None:
            # An unknown step kind is not a mistake to count -- the
            # model produced something outside the schema entirely.
            return consecutive_invalid, consecutive_business_rule, True, None
        try:
            result = handler(step, user_record, visible_schema, gathered, context)
            if isinstance(result, _ProposalPending):
                return 0, 0, True, result.pending
            if result is not STEP_HANDLED:
                gathered.append({**step, "result": result})
            return 0, 0, False, None
        except SubmissionCriteriaViolation as e:
            # MUST be caught before the generic ValueError branch below
            # -- SubmissionCriteriaViolation IS a ValueError subclass,
            # and Python matches except clauses in order; the specific
            # one has to come first or it would never be reached.
            new_count, should_stop = _handle_recoverable_mistake(
                gathered, consecutive_business_rule, self.max_consecutive_invalid_steps,
                detail=f"{step} -- {e}",
                rejected_step_name="rejected_business_rule",
                attempt_label="business rule rejection",
                stop_message="too many consecutive business rule rejections, stopping",
                note=f"That action is not currently allowed: {e}. "
                     f"Try a different action, a different object, or finish if you have enough already.",
            )
            return consecutive_invalid, new_count, should_stop, None
        except (ValueError, TypeError, PermissionError) as e:
            if isinstance(e, TypeError):
                # A TypeError here is far more likely OUR bug than the
                # model's -- a mediator called with the wrong arity, a
                # None where a dict was expected. Treated as a
                # recoverable model mistake it becomes invisible: the
                # model is told its step was invalid, retries, fails
                # again, and the loop stops with "too many consecutive
                # invalid steps" while the real defect never surfaces.
                #
                # Still recovered rather than raised, because a model
                # CAN genuinely provoke one (a nested dict where an id
                # belongs) and crashing a user's query on an ambiguous
                # signal is worse. But logged at error level with a
                # traceback, so it is findable rather than buried among
                # genuine model mistakes at warning level.
                logger.error(f"TypeError executing {step} -- likely a bug, not a bad step",
                             exc_info=True)
            new_count, should_stop = _handle_recoverable_mistake(
                gathered, consecutive_invalid, self.max_consecutive_invalid_steps,
                detail=f"{step} -- {e}",
                rejected_step_name="rejected_invalid_step",
                attempt_label="invalid step",
                stop_message="too many consecutive invalid steps, stopping",
                note=f"That step was invalid: {step} -- {e}. "
                     f"Check the schema above and try something valid, "
                     f"or finish if you have enough already.",
            )
            return new_count, consecutive_business_rule, should_stop, None

    def run(self, user_record: UserRecord, query_text: str,
            cancel_event: threading.Event | None = None,
            context: RequestContext | None = None,
            refresh_user: "Callable[[], UserRecord | None] | None" = None) -> AgentLoopResult:
        # The actual traversal: repeatedly picks a step, executes it,
        # and accumulates results until finish/duplicate-cap/invalid-cap/
        # a proposed write/cancellation/max_hops -- whichever comes
        # first. Each phase is its own method -- _handle_finish_attempt()
        # and _execute_step() -- so this loop reads as a sequence of
        # named decisions rather than one long block.
        #
        # user_record is a pre-resolved UserRecord, not a raw user_id --
        # the caller resolves identity ONCE. cancel_event is checked
        # only at the top of each hop -- see module docstring.
        gathered: list[dict] = []
        seen_signatures = set()
        consecutive_duplicates = 0
        consecutive_invalid = 0
        consecutive_business_rule = 0
        asymmetry_nudged = False
        writes_enabled = self.write_mediator is not None

        # Computed ONCE per run(), not per hop -- same as visible_schema.
        # This is the AUTHORIZATION-filtered set of actions this user
        # may even attempt; it does NOT change mid-request. The
        # separate, per-OBJECT validity annotations _describe_actions()
        # computes from `gathered` ARE necessarily fresh every hop --
        # handled correctly already, since _build_system_prompt() itself
        # is rebuilt fresh on every call to next_step() below, and
        # `gathered` is the same list, growing across hops.
        visible_schema = self.mediator.visible_schema(user_record)
        visible_action_types = self.write_mediator.visible_action_types(user_record) if self.write_mediator else {}

        for _ in range(1, self.max_hops + 1):
            if cancel_event is not None and cancel_event.is_set():
                return AgentLoopResult(gathered=gathered, cancelled=True)

            # THE ACTING USER IS RE-RESOLVED EVERY HOP, not once per
            # request. Identity is resolved once when the request
            # arrives, and on this deployment a query can run for
            # minutes -- long enough for an administrator to disable an
            # account or change a role and reasonably expect it to take
            # effect. Recorded in ROADMAP.md's security backlog before
            # this migration began.
            #
            # A CHANGE STOPS THE LOOP rather than continuing under the
            # new authority, and that is the substantive decision. The
            # alternative -- carry on with the new record -- produces an
            # answer assembled partly under one set of grants and partly
            # under another, which was never authorized as a whole. That
            # is the same objection as a torn read, and as an answer
            # that mixes two data snapshots.
            #
            # Recomputing visible_schema instead was the other option.
            # It has the same defect: the gathered data was read under
            # the old schema and would be reported under the new one.
            if refresh_user is not None:
                current = refresh_user()
                if current is None or current != user_record:
                    # None means the account is gone or disabled. Either
                    # way the work so far is returned: it WAS authorized
                    # when it was read, and discarding it would lose
                    # information the user was entitled to.
                    return AgentLoopResult(gathered=gathered, authority_changed=True)

            step = next_step(
                self.client, query_text, visible_schema, gathered, self.tools, writes_enabled, visible_action_types
            )

            if step["step"] == "finish":
                should_stop, asymmetry_nudged = self._handle_finish_attempt(gathered, asymmetry_nudged)
                if should_stop:
                    break
                continue

            signature = _step_signature(step)
            if signature is not None and signature in seen_signatures:
                consecutive_duplicates, should_stop = _handle_recoverable_mistake(
                    gathered, consecutive_duplicates, self.max_consecutive_duplicates,
                    detail=f"{step}",
                    rejected_step_name="rejected_duplicate",
                    attempt_label="duplicate step",
                    stop_message="too many consecutive duplicates, stopping",
                    note=f"You already have this: {step}. Choose something "
                         f"different, or finish if you have enough.",
                )
                if should_stop:
                    break
                continue

            consecutive_duplicates = 0
            if signature is not None:
                seen_signatures.add(signature)
                if step["step"] == "get_object":
                    # ALSO records each individual field's own get_
                    # field-shaped signature -- closes a real gap
                    # found directly, empirically (not assumed): a
                    # get_object call followed by an ordinary get_
                    # field for ONE of the SAME fields would otherwise
                    # NOT be recognized as a duplicate at all, since
                    # the two step TYPES produce genuinely different
                    # signatures even when they cover overlapping
                    # data (frozenset(field_names) as a whole vs one
                    # single field_name). See this function's own
                    # AI-notes for the reverse, rarer case (get_field
                    # first, then a LARGER get_object covering that
                    # same field among others) this does NOT close.
                    for object_id in _object_ids_in(step):
                        for field_name in step["field_names"]:
                            seen_signatures.add(
                                ("get_field", step["object_type"], object_id, field_name))

            consecutive_invalid, consecutive_business_rule, should_stop, pending_write = self._execute_step(
                step, user_record, visible_schema, gathered, consecutive_invalid,
                consecutive_business_rule, context
            )
            if pending_write is not None:
                return AgentLoopResult(gathered=gathered, pending_write=pending_write)
            if should_stop:
                break
        else:
            # The for loop exhausted every hop without ever break-ing --
            # the model was never given the chance to decide it was
            # done. hit_max_hops tells the caller (and, through it,
            # synthesize_insight()) that whatever WAS gathered may be
            # genuinely incomplete, not just "as much as was needed" --
            # a real, different fact from every other way this loop can
            # end, and one that used to be visible only in a server log
            # a caller would never see.
            logger.warning(f"hit max_hops ({self.max_hops}), stopping")
            return AgentLoopResult(gathered=gathered, hit_max_hops=True)

        return AgentLoopResult(gathered=gathered)
