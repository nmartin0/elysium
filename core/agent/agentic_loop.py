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
(search_object, get_field, or finish), executes it against the
DataMediator, and accumulates results until the model signals
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
from dataclasses import dataclass

from core.concurrency import ConcurrencyLimiter
from core.intermediate_layer.audit import log_access
from core.intermediate_layer.auth import authorize, UserRecord
from core.llm.agent_step_prompt import next_step
from core.deployment_loader import build_llm_adapter
from core.llm.interface import LLMAdapter
from core.ontology.mediator import DataMediator
from core.ontology.submission_criteria import SubmissionCriteriaViolation
from core.ontology.write_mediator import WriteMediator, PendingWrite
from core.tools.interface import Tool
from core.tools.registry import get_enabled_tools

logger = logging.getLogger(__name__)


@dataclass
class AgentLoopResult:
    gathered: list[dict]
    pending_write: PendingWrite | None = None
    cancelled: bool = False
    hit_max_hops: bool = False


def _step_signature(step: dict):
    # A hashable fingerprint of one step, used to detect exact repeats.
    # propose_action has NO entry here -- see module docstring for why a
    # second proposal in one run() is now structurally impossible, not
    # just discouraged.
    if step["step"] == "search_object":
        return ("search_object", step["object_type"], frozenset(step["filter"].items()))
    if step["step"] == "get_field":
        return ("get_field", step["object_type"], step["object_id"], step["field_name"])
    if step["step"] == "use_tool":
        # Tool args can contain UNHASHABLE values (e.g. lists for
        # x_values/y_values) -- frozenset(dict.items()), used for the
        # other step types, would crash on these. JSON serialization
        # (sort_keys=True for determinism) handles nested lists/dicts
        # safely and still produces a stable, hashable signature.
        return ("use_tool", step["tool_name"], json.dumps(step["args"], sort_keys=True))
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


class AgentLoop:
    # Step types that are process bookkeeping, not real gathered data --
    # filter_real_data() strips these before handing results to synthesis.
    BOOKKEEPING_STEPS = frozenset({
        "rejected_duplicate", "completeness_check", "rejected_invalid_step", "rejected_business_rule",
    })

    def __init__(self, client: LLMAdapter, mediator: DataMediator, tools: list[Tool] | None = None,
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
        tools = get_enabled_tools(deployment.enabled_tools)
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

    def _execute_step(self, step: dict, user_record: UserRecord, visible_schema: dict,
                       gathered: list[dict], consecutive_invalid: int, consecutive_business_rule: int
                       ) -> tuple[int, int, bool, PendingWrite | None]:
        # Runs one search_object/get_field/use_tool/propose_action
        # step. Returns (new_consecutive_invalid,
        # new_consecutive_business_rule, should_stop_loop,
        # pending_write_or_None). A non-None pending_write ALWAYS means
        # should_stop_loop is also True -- proposing a write is a
        # terminal action for this run(), same as finishing.
        #
        # TWO independent "consecutive mistake" counters, deliberately
        # -- a business-rule rejection (SubmissionCriteriaViolation) is
        # a genuinely different KIND of event than a plain invalid step
        # (a hallucinated field name, a malformed step): the model was
        # fully authorized and structurally correct, just blocked by
        # the object's own current state. A real success resets BOTH
        # counters; either failure kind leaves the OTHER counter
        # untouched -- neither resets nor increments it. This is what
        # actually delivers on the decision that a business-rule
        # rejection shouldn't count against the same strike cap as
        # genuine confusion.
        try:
            if step["step"] == "search_object":
                # visible_schema passed through explicitly -- already
                # computed ONCE for this whole request by run(), not
                # recomputed on every search_object call.
                result = self.mediator.search_object(
                    user_record, step["object_type"], step["filter"], visible_schema=visible_schema
                )
            elif step["step"] == "get_field":
                result = self.mediator.get_field(
                    user_record, step["object_type"], step["object_id"], step["field_name"]
                )
            elif step["step"] == "use_tool":
                tool = self._tools_by_name.get(step["tool_name"])
                tool_name = step["tool_name"]
                if tool is None:
                    # Same message whether the tool genuinely doesn't
                    # exist in this deployment's enabled set, or exists
                    # but this user lacks tool:<name> -- checked next.
                    raise ValueError(f"Unknown tool: {tool_name!r}")
                action = f"tool:{tool_name}"
                rbac_allowed = authorize(user_record, self.mediator.roles, action)
                log_access(user_record.user_id, "tool", tool_name, action, mac_allowed=True, rbac_allowed=rbac_allowed)
                if not rbac_allowed:
                    # DELIBERATELY the exact same message as "tool
                    # doesn't exist" above -- distinguishing the two
                    # would let a user probe which tools exist.
                    raise ValueError(f"Unknown tool: {tool_name!r}")
                with self._tool_limiters[tool.name].limit():
                    result = tool.run(**step["args"])
            elif step["step"] == "propose_action":
                # The NAMED-action-type proposal path -- see
                # core/ontology/write_mediator.py's propose_action() for
                # the full mechanism. Stops the loop immediately;
                # confirmation/execution is always the caller's job.
                if self.write_mediator is None:
                    raise ValueError("Writes are not enabled for this deployment")
                pending = self.write_mediator.propose_action(
                    user_record, step["action_type"], step.get("object_id"), step["parameters"]
                )
                return 0, 0, True, pending
            else:
                return consecutive_invalid, consecutive_business_rule, True, None  # shouldn't happen -- agent_step_prompt already validates this

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
            cancel_event: threading.Event | None = None) -> AgentLoopResult:
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
        gathered = []
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

            consecutive_invalid, consecutive_business_rule, should_stop, pending_write = self._execute_step(
                step, user_record, visible_schema, gathered, consecutive_invalid, consecutive_business_rule
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
