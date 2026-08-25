"""
agentic_loop.py  (the agentic loop -- org-agnostic)

AgentLoop bundles everything that stays FIXED across every query for a
given deployment -- the LLMAdapter, the DataMediator, and the hop/
retry limits -- into one object, constructed once. Only run() takes the
truly per-call arguments (user_id, query_text). This used to be a
single function re-passed all seven of these on every call; per-call
that's the same "same parameters, many calls" pattern that means a
class fits better than a function.

Repeatedly asks core/llm/agent_step_prompt.py for the next step
(search_object, get_field, or finish), executes it against the
DataMediator, and accumulates results until the model signals
"finish", asks for something it already has (duplicate detection), asks
for something invalid (invalid-step recovery), or max_hops is reached.

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

GAP CLOSED (this used to be documented here as a KNOWN GAP -- worth
keeping the history visible): every read this loop performs goes
through DataMediator, which enforces BOTH MAC (region/org boundary) and
RBAC (role -> allowed_actions) on every object touched, and audits every
decision via core/intermediate_layer/access_control.py's check_access().
The old core/intermediate_layer/gateway.py/action_registry.py files,
which auth/audit were never actually connected to, are gone -- their
entire purpose is now handled correctly, per-object, inline.

Used by: scripts/run_deployment.py, and directly by
         tests/integration/ (or whatever replaces it)
"""

import json
import logging
from typing import Callable

from core.concurrency import ConcurrencyLimiter
from core.intermediate_layer.audit import log_access
from core.intermediate_layer.auth import authorize
from core.llm.agent_step_prompt import next_step
from core.deployment_loader import build_llm_adapter
from core.llm.interface import LLMAdapter
from core.ontology.mediator import DataMediator
from core.ontology.write_mediator import WriteMediator, PendingWrite
from core.tools.interface import Tool
from core.tools.registry import get_enabled_tools

logger = logging.getLogger(__name__)


def _step_signature(step: dict):
    # A hashable fingerprint of one step, used to detect exact repeats.
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
    if step["step"] == "propose_write":
        # Same unhashable-values concern as use_tool -- changes can
        # contain arbitrary values. Deliberately NOT deduplicating
        # identical write proposals across a whole run() the way other
        # steps are -- a user might legitimately want to update the
        # same object twice with different values in one conversation.
        # This only catches an EXACT repeat (same object, same action,
        # same literal changes), which is still worth blocking (almost
        # certainly a stuck model, not an intentional double-write).
        return (
            "propose_write", step["object_type"], step.get("object_id"),
            step["action"], json.dumps(step["changes"], sort_keys=True),
        )
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
    # if the cap is hit. `detail`/`attempt_label`/`stop_message` are each
    # passed in verbatim rather than derived (e.g. by pluralizing
    # attempt_label) -- the two original messages never shared a
    # consistent grammar rule ("duplicate step" vs "duplicates" at the
    # cap), so deriving one from the other would silently change the text.
    # Returns (new_count, should_stop) -- the caller does the actual
    # break, since a function can't break its caller's loop directly.
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
        "rejected_duplicate", "completeness_check", "rejected_invalid_step",
    })

    def __init__(self, client: LLMAdapter, mediator: DataMediator, tools: list[Tool] | None = None,
                 write_mediator: WriteMediator | None = None,
                 confirm_write: Callable[[PendingWrite], bool] | None = None,
                 max_hops: int = 8, max_consecutive_duplicates: int = 2,
                 max_consecutive_invalid_steps: int = 2):
        # These stay fixed across every query this loop instance ever
        # runs -- constructed once per deployment, then run() called
        # once per actual user question. tools defaults to None, not []
        # -- the classic Python mutable-default-argument trap: a literal
        # [] default would be created ONCE at function definition and
        # silently shared across every AgentLoop that didn't pass its
        # own tools list.
        #
        # write_mediator/confirm_write default to None/None -- writes
        # are OPT-IN, unlike data/LLM/tools which every deployment
        # needs. Both None means this loop simply never proposes writes
        # (see agent_step_prompt.py's writes_enabled flag).
        self.client = client
        self.mediator = mediator
        self.tools = tools if tools is not None else []
        self._tools_by_name = {tool.name: tool for tool in self.tools}
        self._tool_limiters = {
            tool.name: ConcurrencyLimiter(tool.max_concurrent_calls) for tool in self.tools
        }
        self.write_mediator = write_mediator
        self.confirm_write = confirm_write
        self.max_hops = max_hops
        self.max_consecutive_duplicates = max_consecutive_duplicates
        self.max_consecutive_invalid_steps = max_consecutive_invalid_steps

    @classmethod
    def from_deployment(cls, deployment, mediator: DataMediator,
                         write_mediator: WriteMediator | None = None,
                         confirm_write: Callable[[PendingWrite], bool] | None = None) -> "AgentLoop":
        # The standard way every caller should build an AgentLoop -- one
        # authoritative place reading deployment.max_hops etc., instead
        # of every call site (scripts/run_deployment.py, integration
        # tests) separately copy-pasting the same construction and
        # risking drift if a new tuning parameter is ever added.
        # write_mediator/confirm_write are NOT built here automatically
        # (unlike tools) -- constructing a WriteMediator needs a real
        # confirm_write implementation (a terminal prompt, a UI callback,
        # etc.) that only the caller can supply; a caller not passing
        # them gets a loop with writes fully disabled, which is the
        # correct default.
        client = build_llm_adapter(deployment, deployment.step_model)
        tools = get_enabled_tools(deployment.enabled_tools)
        return cls(
            client, mediator, tools=tools,
            write_mediator=write_mediator, confirm_write=confirm_write,
            max_hops=deployment.max_hops,
            max_consecutive_duplicates=deployment.max_consecutive_duplicates,
            max_consecutive_invalid_steps=deployment.max_consecutive_invalid_steps,
        )

    @staticmethod
    def filter_real_data(gathered: list[dict]) -> list[dict]:
        # Strips process bookkeeping entries from a run() result, leaving
        # only real search_object/get_field results -- what should
        # actually be handed to synthesis.
        return [item for item in gathered if item["step"] not in AgentLoop.BOOKKEEPING_STEPS]

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

    def _execute_step(self, step: dict, user_id: str,
                       gathered: list[dict], consecutive_invalid: int) -> tuple[int, bool]:
        # Runs one search_object/get_field/use_tool/propose_write step,
        # appending the result to `gathered` on success. On a recoverable
        # failure (ValueError from mediator/tool validation, TypeError
        # from a tool called with wrong argument names, or PermissionError
        # from a denied write proposal), hands off to the shared
        # recoverable-mistake handler -- ALL of these are the SAME
        # conceptual event ("the model attempted an action and it
        # failed"), not separately-tracked failure modes. A permission
        # denial reported this way is a UX choice about how the loop
        # informs the model, not a security weakening -- the actual
        # blocking already happened correctly inside DataMediator/
        # WriteMediator before this ever runs. Returns
        # (new_consecutive_invalid, should_stop_loop).
        try:
            if step["step"] == "search_object":
                result = self.mediator.search_object(user_id, step["object_type"], step["filter"])
            elif step["step"] == "get_field":
                result = self.mediator.get_field(
                    user_id, step["object_type"], step["object_id"], step["field_name"]
                )
            elif step["step"] == "use_tool":
                tool = self._tools_by_name.get(step["tool_name"])
                tool_name = step["tool_name"]
                if tool is None:
                    # Same message whether the tool genuinely doesn't
                    # exist in this deployment's enabled set, or exists
                    # but this user lacks tool:<name> -- checked next.
                    # No audit entry here: there's genuinely nothing to
                    # log yet, since the name isn't even a real,
                    # resolvable tool in this deployment.
                    raise ValueError(f"Unknown tool: {tool_name!r}")
                action = f"tool:{tool_name}"
                rbac_allowed = authorize(self.mediator.users, self.mediator.roles, user_id, action)
                # Tools have no MAC dimension (no region/org boundary to
                # check) -- mac_allowed=True is "not applicable," the
                # same convention already used for create: actions.
                log_access(user_id, "tool", tool_name, action, mac_allowed=True, rbac_allowed=rbac_allowed)
                if not rbac_allowed:
                    # DELIBERATELY the exact same message as "tool
                    # doesn't exist" above -- distinguishing the two
                    # would let a user probe which tools exist in this
                    # deployment by testing names and watching which
                    # error differs.
                    raise ValueError(f"Unknown tool: {tool_name!r}")
                with self._tool_limiters[tool.name].limit():
                    result = tool.run(**step["args"])
            elif step["step"] == "propose_write":
                if self.write_mediator is None or self.confirm_write is None:
                    raise ValueError("Writes are not enabled for this deployment")
                pending = self.write_mediator.propose_write(
                    user_id, step["object_type"], step.get("object_id"), step["action"], step["changes"]
                )
                approved = self.confirm_write(pending)
                result = self.write_mediator.confirm_and_execute(pending, approved)
            else:
                return consecutive_invalid, True  # shouldn't happen -- agent_step_prompt already validates this

            gathered.append({**step, "result": result})
            return 0, False
        except (ValueError, TypeError, PermissionError) as e:
            return _handle_recoverable_mistake(
                gathered, consecutive_invalid, self.max_consecutive_invalid_steps,
                detail=f"{step} -- {e}",
                rejected_step_name="rejected_invalid_step",
                attempt_label="invalid step",
                stop_message="too many consecutive invalid steps, stopping",
                note=f"That step was invalid: {step} -- {e}. "
                     f"Check the schema above and try something valid, "
                     f"or finish if you have enough already.",
            )

    def run(self, user_id: str, query_text: str) -> list[dict]:
        # The actual traversal: repeatedly picks a step, executes it,
        # and accumulates results until finish/duplicate-cap/invalid-cap/
        # max_hops -- whichever comes first. Returns everything gathered,
        # including process bookkeeping entries the caller should filter
        # out before handing this to synthesis. Each phase (finishing,
        # executing) is its own method -- _handle_finish_attempt() and
        # _execute_step() -- so this loop reads as a sequence of named
        # decisions rather than one long block.
        #
        # user_id is now the ONLY identity parameter -- DataMediator
        # resolves everything else (the MAC security value, the RBAC
        # role) internally via check_access(). Callers no longer
        # separately pre-resolve a security value before calling in.
        gathered = []
        seen_signatures = set()
        consecutive_duplicates = 0
        consecutive_invalid = 0
        asymmetry_nudged = False
        writes_enabled = self.write_mediator is not None and self.confirm_write is not None

        # Computed ONCE per run(), not per hop -- a role isn't expected
        # to change mid-request, and this is what the LLM's prompt is
        # built from for every hop of this one query. THE canonical
        # "what does this user get to know exists" -- see
        # DataMediator.visible_schema()'s own docstring.
        visible_schema = self.mediator.visible_schema(user_id)

        # `_` is idiomatic Python for "intentionally unused loop variable"
        # -- max_hops caps how many times this can run, but the count
        # itself is never read inside the loop.
        for _ in range(1, self.max_hops + 1):
            step = next_step(self.client, query_text, visible_schema, gathered, self.tools, writes_enabled)

            if step["step"] == "finish":
                should_stop, asymmetry_nudged = self._handle_finish_attempt(gathered, asymmetry_nudged)
                if should_stop:
                    break
                continue

            signature = _step_signature(step)
            if signature in seen_signatures:
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
            seen_signatures.add(signature)

            consecutive_invalid, should_stop = self._execute_step(
                step, user_id, gathered, consecutive_invalid
            )
            if should_stop:
                break
        else:
            logger.warning(f"hit max_hops ({self.max_hops}), stopping")

        return gathered
