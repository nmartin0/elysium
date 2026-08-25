"""
agentic_loop.py  (the agentic loop -- org-agnostic)

AgentLoop bundles everything that stays FIXED across every query for a
given deployment -- the LLMAdapter, the DataMediator, and the hop/
retry limits -- into one object, constructed once. Only run() takes the
truly per-call arguments (user_security_value, query_text). This used to be a
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

KNOWN GAP (flagged deliberately, not an oversight): this loop does NOT
go through core/intermediate_layer/gateway.py, so auth.authorize() and
audit logging are bypassed here for now. Region/security scoping still
holds -- that enforcement lives inside DataMediator itself, not in
the gateway. Reconnecting this loop to auth/audit is a real task for
later, not automatic.

Used by: scripts/run_deployment.py, and directly by
         tests/integration/ (or whatever replaces it)
"""

import json
import logging

from core.llm.agent_step_prompt import next_step
from core.deployment_loader import build_llm_adapter
from core.llm.interface import LLMAdapter
from core.ontology.mediator import DataMediator
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
                 max_hops: int = 8, max_consecutive_duplicates: int = 2,
                 max_consecutive_invalid_steps: int = 2):
        # These stay fixed across every query this loop instance ever
        # runs -- constructed once per deployment, then run() called
        # once per actual user question. tools defaults to None, not []
        # -- the classic Python mutable-default-argument trap: a literal
        # [] default would be created ONCE at function definition and
        # silently shared across every AgentLoop that didn't pass its
        # own tools list.
        self.client = client
        self.mediator = mediator
        self.tools = tools if tools is not None else []
        self._tools_by_name = {tool.name: tool for tool in self.tools}
        self.max_hops = max_hops
        self.max_consecutive_duplicates = max_consecutive_duplicates
        self.max_consecutive_invalid_steps = max_consecutive_invalid_steps

    @classmethod
    def from_deployment(cls, deployment, mediator: DataMediator) -> "AgentLoop":
        # The standard way every caller should build an AgentLoop -- one
        # authoritative place reading deployment.max_hops etc., instead
        # of every call site (scripts/run_deployment.py, integration
        # tests) separately copy-pasting the same construction and
        # risking drift if a new tuning parameter is ever added.
        client = build_llm_adapter(deployment, deployment.step_model)
        tools = get_enabled_tools(deployment.enabled_tools)
        return cls(
            client, mediator, tools=tools,
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

    def _execute_step(self, step: dict, user_security_value: str,
                       gathered: list[dict], consecutive_invalid: int) -> tuple[int, bool]:
        # Runs one search_object/get_field/use_tool step, appending the
        # result to `gathered` on success. On a recoverable failure
        # (ValueError from mediator/tool validation, or TypeError from a
        # tool called with the wrong argument names), hands off to the
        # shared recoverable-mistake handler -- a tool execution failure
        # is treated as the SAME conceptual event as an invalid schema
        # step ("the model attempted an action and it failed"), not a
        # separately-tracked failure mode. Returns (new_consecutive_invalid,
        # should_stop_loop).
        try:
            if step["step"] == "search_object":
                result = self.mediator.search_object(user_security_value, step["object_type"], step["filter"])
            elif step["step"] == "get_field":
                result = self.mediator.get_field(
                    user_security_value, step["object_type"], step["object_id"], step["field_name"]
                )
            elif step["step"] == "use_tool":
                tool = self._tools_by_name.get(step["tool_name"])
                if tool is None:
                    raise ValueError(f"Unknown tool: {step['tool_name']!r}")
                result = tool.run(**step["args"])
            else:
                return consecutive_invalid, True  # shouldn't happen -- agent_step_prompt already validates this

            gathered.append({**step, "result": result})
            return 0, False
        except (ValueError, TypeError) as e:
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

    def run(self, user_security_value: str, query_text: str) -> list[dict]:
        # The actual traversal: repeatedly picks a step, executes it,
        # and accumulates results until finish/duplicate-cap/invalid-cap/
        # max_hops -- whichever comes first. Returns everything gathered,
        # including process bookkeeping entries the caller should filter
        # out before handing this to synthesis. Each phase (finishing,
        # executing) is its own method -- _handle_finish_attempt() and
        # _execute_step() -- so this loop reads as a sequence of named
        # decisions rather than one long block.
        gathered = []
        seen_signatures = set()
        consecutive_duplicates = 0
        consecutive_invalid = 0
        asymmetry_nudged = False

        # `_` is idiomatic Python for "intentionally unused loop variable"
        # -- max_hops caps how many times this can run, but the count
        # itself is never read inside the loop.
        for _ in range(1, self.max_hops + 1):
            step = next_step(self.client, query_text, self.mediator.schema, gathered, self.tools)

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
                step, user_security_value, gathered, consecutive_invalid
            )
            if should_stop:
                break
        else:
            logger.warning(f"hit max_hops ({self.max_hops}), stopping")

        return gathered
