"""
agent_step_prompt.py  (the agent loop's per-hop LLM call -- org-agnostic)

Unlike a single-shot router, this is called repeatedly by
core/agent/agentic_loop.py's AgentLoop. Each call sees the original question
plus everything gathered so far, and returns exactly one of:

  {"step": "search_object", "object_type": ..., "filter": {...}}
  {"step": "get_field", "object_type": ..., "object_id": ..., "field_name": ...}
  {"step": "finish"}

The schema describing available object types/fields is rendered into the
prompt dynamically from whatever `schema` dict is passed in -- no object
type names are hardcoded here, so this file works unchanged for any
deployment's ontology.

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
from core.tools.interface import Tool

logger = logging.getLogger(__name__)

FINISH_STEP = {"step": "finish"}


def _describe_object_type(object_type: str, definition: dict) -> str:
    # Builds the prompt block for ONE object type: its fields (data vs
    # link), which of them are searchable, and a note about any
    # link-only (reverse link) fields that can't be searched directly.
    id_field = definition["id_field"]
    searchable = [id_field]
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

    block = (
        f"- {object_type}: identified by {id_field!r}. "
        f"Fields: " + ", ".join(field_descriptions) + "\n"
        f"  You may search_object using any of: {searchable} "
        f'(e.g. {{"step": "search_object", "object_type": "{object_type}", '
        f'"filter": {{"{searchable[-1]}": "<value>"}}}})'
    )
    if link_only:
        block += (
            f"\n  {link_only} cannot be searched directly -- reach them with "
            f"get_field on an object you already have the ID for."
        )
    return block


def _describe_schema(schema: dict) -> str:
    # Renders the schema into plain-English prompt text: one block per
    # object type, built by _describe_object_type().
    return "\n".join(
        _describe_object_type(object_type, definition)
        for object_type, definition in schema.items()
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


def _build_system_prompt(schema: dict, tools: list[Tool], writes_enabled: bool) -> str:
    tools_section = ""
    if tools:
        tools_section = f"""

You also have access to these computational tools:

{_describe_tools(tools)}

To use one:
  {{"step": "use_tool", "tool_name": "<name>", "args": {{...}}}}
"""
    writes_section = ""
    if writes_enabled:
        writes_section = """

You may also propose a WRITE to update an existing object, or create a
new one. A write only takes effect after a human explicitly confirms
it -- propose one only when the question genuinely calls for changing
data, never merely to answer a question.

To propose updating an existing object:
  {"step": "propose_write", "object_type": "<type>", "object_id": "<id>", "action": "update", "changes": {"<field>": "<new_value>"}}

To propose creating a new object:
  {"step": "propose_write", "object_type": "<type>", "action": "create", "changes": {"<field>": "<value>", ...}}
"""
    return f"""You gather information step by step to answer a question,
using ONLY these object types and fields:

{_describe_schema(schema)}
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


def next_step(client: LLMAdapter, query_text: str, schema: dict,
              gathered_so_far: list[dict], tools: list[Tool], writes_enabled: bool) -> dict:
    # Asks the model for exactly one next step, and validates that the
    # JSON response has the right KEYS for its step type -- NOT that
    # object_type/field_name are real entries in the ontology schema
    # (that check happens later, inside DataMediator; a bad value here
    # surfaces back to core/agent/agentic_loop.py as a caught ValueError). Fails
    # closed (returns finish) on ANY uncertainty -- malformed JSON, an
    # unrecognized step, missing keys. tools is required (not defaulted
    # to []) to avoid the classic Python mutable-default-argument trap.
    # writes_enabled is likewise required, not defaulted -- an explicit
    # capability flag, not something to silently infer.
    user_message = (
        f"Question: {query_text}\n\n"
        f"Gathered so far: {json.dumps(gathered_so_far)}\n\n"
        f"What is the next step?"
    )

    try:
        raw_content = client.chat(
            _build_system_prompt(schema, tools, writes_enabled), user_message,
            json_mode=True, temperature=0,
        )
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

    if step == "propose_write":
        required = {"object_type", "action", "changes"}
        if not required.issubset(parsed.keys()):
            logger.warning("malformed propose_write step, finishing")
            return FINISH_STEP
        if parsed["action"] not in ("update", "create"):
            logger.warning(f"invalid write action {parsed['action']!r}, finishing")
            return FINISH_STEP
        if parsed["action"] == "update" and "object_id" not in parsed:
            logger.warning("propose_write update missing object_id, finishing")
            return FINISH_STEP
        return {
            "step": "propose_write",
            "object_type": parsed["object_type"],
            "object_id": parsed.get("object_id"),
            "action": parsed["action"],
            "changes": parsed["changes"],
        }

    logger.warning(f"unrecognized step {step!r}, finishing")
    return FINISH_STEP
