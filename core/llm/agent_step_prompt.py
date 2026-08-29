"""
agent_step_prompt.py  (the agent loop's per-hop LLM call -- org-agnostic)

Unlike a single-shot router, this is called repeatedly by
core/agent/agentic_loop.py's AgentLoop. Each call sees the original question
plus everything gathered so far, and returns exactly one of:

  {"step": "search_object", "object_type": ..., "filter": {...}}
  {"step": "get_field", "object_type": ..., "object_id": ..., "field_name": ...}
  {"step": "finish"}

The schema describing available object types/fields is rendered into the
prompt dynamically from whatever ALREADY-FILTERED `visible_schema` dict
is passed in -- see core/ontology/mediator.py's visible_schema() method,
the single source of truth for what a given user is authorized to know
exists at all. No object type names are hardcoded here, so this file
works unchanged for any deployment's ontology, and it never sees an
object type or field the caller didn't already decide this user may
know about.

Takes an LLMAdapter explicitly (not a model/url/timeout triple) --
callers own one client and hand it in, same explicit-dependency style
used throughout core/.

Fails CLOSED: any uncertainty (bad JSON, unknown action, missing
params) results in returning "no action" rather than guessing or
passing through something we're not sure about.

Called by: core/agent/agentic_loop.py
"""

import json
import logging

import requests

from core.llm.interface import LLMAdapter
from core.ontology.schema import is_searchable_field
from core.ontology.submission_criteria import SubmissionCriteriaViolation, evaluate_submission_criteria
from core.tools.interface import Tool

logger = logging.getLogger(__name__)

FINISH_STEP = {"step": "finish"}


def _describe_object_type(object_type: str, definition: dict) -> str:
    # Builds the prompt block for ONE object type: its fields (data vs
    # link), which of them are searchable, and a note about any
    # link-only (reverse link) fields that can't be searched directly.
    #
    # id_field may be None -- the identifier itself needs its own
    # explicit grant like any other field (see DataMediator.
    # visible_schema()'s docstring for why an identifier isn't
    # automatically safe to expose). Handled explicitly here rather
    # than assumed present, since the example filter line below would
    # otherwise crash on an empty searchable list.
    id_field = definition["id_field"]
    searchable = [id_field] if id_field is not None else []
    link_only = []
    field_descriptions = []

    for field_name, field_info in definition["fields"].items():
        if field_info["type"] == "link":
            field_descriptions.append(f"{field_name} (link -> {field_info['target']})")
        else:
            field_descriptions.append(f"{field_name} (data)")

        # Same rule core/ontology/mediator.py enforces for real --
        # see is_searchable_field()'s docstring for why this can't be
        # computed independently in two places.
        if is_searchable_field(field_info):
            searchable.append(field_name)
        elif field_info["type"] == "link":
            link_only.append(field_name)

    identifier_note = f"identified by {id_field!r}. " if id_field is not None else ""
    field_list = ", ".join(field_descriptions) if field_descriptions else "(none visible)"

    if searchable:
        search_example = (
            f"\n  You may search_object using any of: {searchable} "
            f'(e.g. {{"step": "search_object", "object_type": "{object_type}", '
            f'"filter": {{"{searchable[-1]}": "<value>"}}}})'
        )
    else:
        # No id_field grant AND no searchable data/link fields -- this
        # type can still be reached via a link FROM another object
        # (get_field on something else that points to it), just not
        # discovered directly via search_object.
        search_example = "\n  Cannot be searched directly -- reachable only via a link from another object."

    block = f"- {object_type}: {identifier_note}Fields: {field_list}{search_example}"
    if link_only:
        block += (
            f"\n  {link_only} cannot be searched directly -- reach them with "
            f"get_field on an object you already have the ID for."
        )
    return block


def _describe_schema(visible_schema: dict) -> str:
    # Renders the ALREADY-FILTERED schema into plain-English prompt
    # text -- one block per object type, built by _describe_object_type().
    # The caller (next_step()) is responsible for filtering; this
    # function simply describes whatever it is given, hidden or not.
    return "\n".join(
        _describe_object_type(object_type, definition)
        for object_type, definition in visible_schema.items()
    )


def _describe_tools(tools: list[Tool]) -> str:
    # Renders available tools into prompt text, generated from each
    # Tool's own name/description/parameters -- never hardcoded, so
    # this works unchanged for any deployment's enabled tool set.
    blocks = []
    for tool in tools:
        params_desc = ", ".join(f'"{p}": <{info["type"]}>' for p, info in tool.parameters.items())
        param_notes = "\n".join(f"    {p}: {info['description']}" for p, info in tool.parameters.items())
        blocks.append(
            f"- {tool.name}: {tool.description}\n"
            f"  Parameters:\n{param_notes}\n"
            f'  (e.g. {{"step": "use_tool", "tool_name": "{tool.name}", "args": {{{params_desc}}}}})'
        )
    return "\n".join(blocks)


def _known_state_for_object(gathered: list[dict], object_type: str, object_id) -> dict:
    # Every field ALREADY read for this specific object during this
    # same run(), keyed by field_name -- built entirely from real
    # get_field results already sitting in `gathered`, never a fresh
    # database read at prompt-build time.
    return {
        item["field_name"]: item["result"]
        for item in gathered
        if item.get("step") == "get_field"
        and item.get("object_type") == object_type
        and item.get("object_id") == object_id
    }


def _action_validity_for_object(action_def: dict, known_state: dict) -> tuple[bool, str] | None:
    # Returns (is_valid, reason) if `known_state` genuinely covers
    # EVERY field this action's own current_state criteria reference --
    # reusing evaluate_submission_criteria() directly, the SAME
    # function propose_action() itself calls at proposal time, not a
    # separate reimplementation that could silently drift out of sync
    # with it over time (the exact risk this project has been careful
    # to avoid elsewhere -- see is_searchable_field()'s own docstring
    # for the earlier instance of this same principle). Returns None
    # if known_state is missing even ONE needed field -- a PARTIAL read
    # must never produce a confident verdict either way, since
    # evaluating a missing field as None could silently produce a
    # WRONG answer depending on the criterion's own operator (e.g. a
    # "not_equals" criterion would incorrectly read as satisfied
    # against a field that was simply never read at all).
    criteria = action_def.get("submission_criteria", [])
    needed_fields = {c["field"] for c in criteria if c["check"] == "current_state"}
    if not needed_fields.issubset(known_state.keys()):
        return None
    try:
        evaluate_submission_criteria(criteria, known_state, {})
        return True, ""
    except SubmissionCriteriaViolation as e:
        return False, str(e)


def _describe_actions(visible_action_types: dict, gathered: list[dict]) -> str:
    # Renders the model-facing named-action vocabulary -- one block per
    # action this user is authorized for (already filtered by
    # WriteMediator.visible_action_types() BEFORE this is ever called;
    # this function has no authorization logic of its own).
    #
    # For any object the model has ALREADY read enough state for
    # during this same run, annotates whether the action is currently
    # valid or blocked (and why) for that specific object -- the
    # hybrid design: cheap and precise when state is already known
    # (mirroring how a real UI can disable/hide an action button for
    # an object already loaded on screen), and silently absent
    # otherwise (an action with no annotatable objects yet -- the
    # common case, e.g. at the very start of a request, before any
    # object's state has been read at all -- is shown with no verdict,
    # exactly as a UI with nothing loaded yet would show it).
    blocks = []
    for action_name, action_def in visible_action_types.items():
        object_type = action_def["object_type"]
        params = action_def.get("parameters", {})
        param_desc = ", ".join(
            f"{name} ({info['type']}{', required' if info.get('required') else ', optional'})"
            for name, info in params.items()
        ) or "no parameters"
        param_json = ", ".join(f'"{name}": "<value>"' for name in params)

        known_object_ids = sorted({
            item["object_id"] for item in gathered
            if item.get("step") == "get_field" and item.get("object_type") == object_type
        }, key=str)

        valid_for, blocked_for = [], []
        for object_id in known_object_ids:
            verdict = _action_validity_for_object(action_def, _known_state_for_object(gathered, object_type, object_id))
            if verdict is None:
                continue
            is_valid, reason = verdict
            if is_valid:
                valid_for.append(str(object_id))
            else:
                blocked_for.append(f"{object_id} ({reason})")

        block = (
            f'- {action_name} (on {object_type}): requires {param_desc}\n'
            f'  {{"step": "propose_action", "action_type": "{action_name}", '
            f'"object_id": "<id>", "parameters": {{{param_json}}}}}'
        )
        if valid_for:
            block += f"\n  Currently valid for: {', '.join(valid_for)}"
        if blocked_for:
            block += f"\n  Currently blocked for: {'; '.join(blocked_for)}"
        blocks.append(block)
    return "\n".join(blocks)


def _build_system_prompt(visible_schema: dict, tools: list[Tool], writes_enabled: bool,
                          visible_action_types: dict, gathered: list[dict]) -> str:
    tools_section = ""
    if tools:
        tools_section = f"""

You also have access to these computational tools:

{_describe_tools(tools)}

To use one:
  {{"step": "use_tool", "tool_name": "<name>", "args": {{...}}}}
"""
    writes_section = ""
    if writes_enabled and visible_action_types:
        # Only present at all if writes are enabled for this deployment
        # AND this user has at least one visible named action -- same
        # gating discipline as tools_section above (an empty section is
        # worse than no section).
        writes_section = f"""

You may also invoke a NAMED ACTION on an object you have access to. An
action only takes effect after a human explicitly confirms it -- invoke
one only when the question genuinely calls for it, never merely to
answer a question. If an action below is marked "Currently blocked"
for a specific object, invoking it for that object will fail -- prefer
a different action or a different object instead.

{_describe_actions(visible_action_types, gathered)}
"""
    return f"""You gather information step by step to answer a question,
using ONLY these object types and fields:

{_describe_schema(visible_schema)}
{tools_section}{writes_section}
At each step, respond with ONLY one JSON object, in one of these shapes:

To find object(s) by any of their searchable fields listed above:
  {{"step": "search_object", "object_type": "<type>", "filter": {{"<field>": "<value>"}}}}

To read one field of an object you already have the ID for (a link
field's value is another object's ID -- you can search_object or
get_field on it next):
  {{"step": "get_field", "object_type": "<type>", "object_id": "<id>", "field_name": "<field>"}}

If you have gathered enough to answer the question, or nothing further
would help:
  {{"step": "finish"}}

IMPORTANT: Before choosing a step, check "Gathered so far" in the user
message. Never request a field you have already gathered for the same
object -- if you find yourself about to repeat something, respond with
finish instead.

IMPORTANT: If a previous get_field result is a LIST of IDs (this means
you followed a link with multiple targets), your next steps should be
get_field calls on those INDIVIDUAL IDs to read the actual data you
need (e.g. amount, date) -- do NOT request the same link field again.

Example: to answer "What is cust_001's email", the correct sequence is:
  1. {{"step": "search_object", "object_type": "Customer", "filter": {{"customer_id": "cust_001"}}}}
  2. {{"step": "get_field", "object_type": "Customer", "object_id": "cust_001", "field_name": "email"}}
  3. {{"step": "finish"}}  <- stop here, do NOT request "email" or any other field again.

Example: to answer "What are cust_001's transaction amounts", after you
get_field "transactions" on Customer cust_001 and receive [1, 2], the
correct next steps are:
  {{"step": "get_field", "object_type": "Transaction", "object_id": 1, "field_name": "amount"}}
  {{"step": "get_field", "object_type": "Transaction", "object_id": 2, "field_name": "amount"}}
  then {{"step": "finish"}} -- NOT another get_field on "transactions".

IMPORTANT: Before you finish, check EVERY ID from a list result (like
[1, 2] above) has been asked about EQUALLY. If you fetched a field for
ID 1 but not the same field for ID 2, that's incomplete -- go back and
get it for ID 2 too before finishing. Do not answer about some items in
a list and silently skip others.
"""


def next_step(client: LLMAdapter, query_text: str, visible_schema: dict,
              gathered_so_far: list[dict], tools: list[Tool], writes_enabled: bool,
              visible_action_types: dict) -> dict:
    # Asks the model for exactly one next step, and validates that the
    # JSON response has the right KEYS for its step type -- NOT that
    # object_type/field_name are real entries in the ontology schema
    # (that check happens later, inside DataMediator; a bad value here
    # surfaces back to core/agent/agentic_loop.py as a caught ValueError). Fails
    # closed (returns finish) on ANY uncertainty -- malformed JSON, an
    # unrecognized step, missing keys. tools is required (not defaulted
    # to []) to avoid the classic Python mutable-default-argument trap.
    # writes_enabled and visible_action_types are likewise required,
    # not defaulted -- explicit capability flags, not something to
    # silently infer (an empty {} is a legitimate, common value --
    # "writes enabled but no named actions declared yet" -- so the
    # caller must pass it explicitly rather than this function
    # guessing at an appropriate default).
    user_message = (
        f"Question: {query_text}\n\n"
        f"Gathered so far: {json.dumps(gathered_so_far)}\n\n"
        f"What is the next step?"
    )

    try:
        raw_content = client.chat(
            _build_system_prompt(visible_schema, tools, writes_enabled, visible_action_types, gathered_so_far),
            user_message,
            json_mode=True, temperature=0,
        )
        # Logs the model's raw response BEFORE any parsing/validation --
        # silent by default (DEBUG), but genuinely valuable when a step's
        # PARSED result looks wrong: this is the only way to tell "the
        # model generated something subtly different than the parsed
        # trace suggests" apart from "our own parsing/validation logic
        # is wrong" -- two very different bugs that look identical from
        # gathered[] alone. Enable with pytest's --log-cli-level=DEBUG.
        logger.debug(f"raw model response: {raw_content!r}")
        parsed = json.loads(raw_content)
    except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
        logger.warning(f"request/parse failed, finishing: {e}")
        return FINISH_STEP

    step = parsed.get("step")

    if step == "finish":
        return FINISH_STEP

    if step == "search_object":
        if "object_type" not in parsed or "filter" not in parsed:
            logger.warning("malformed search_object step, finishing")
            return FINISH_STEP
        return {"step": "search_object", "object_type": parsed["object_type"], "filter": parsed["filter"]}

    if step == "get_field":
        required = {"object_type", "object_id", "field_name"}
        if not required.issubset(parsed.keys()):
            logger.warning("malformed get_field step, finishing")
            return FINISH_STEP
        return {
            "step": "get_field",
            "object_type": parsed["object_type"],
            "object_id": parsed["object_id"],
            "field_name": parsed["field_name"],
        }

    if step == "use_tool":
        if "tool_name" not in parsed or "args" not in parsed:
            logger.warning("malformed use_tool step, finishing")
            return FINISH_STEP
        return {"step": "use_tool", "tool_name": parsed["tool_name"], "args": parsed["args"]}

    if step == "propose_action":
        # Structural validation ONLY -- same discipline as every other
        # step above: whether action_type is a real, authorized named
        # action is NOT checked here, it's WriteMediator.propose_action()'s
        # job, surfacing back to core/agent/agentic_loop.py as a caught
        # ValueError/PermissionError exactly like an unknown object_type
        # or field_name already does for the other step kinds.
        # object_id is genuinely OPTIONAL here -- a "create"-operation
        # action has no existing object to reference at all.
        required = {"action_type", "parameters"}
        if not required.issubset(parsed.keys()):
            logger.warning("malformed propose_action step, finishing")
            return FINISH_STEP
        return {
            "step": "propose_action",
            "action_type": parsed["action_type"],
            "object_id": parsed.get("object_id"),
            "parameters": parsed["parameters"],
        }

    logger.warning(f"unrecognized step {step!r}, finishing")
    return FINISH_STEP
