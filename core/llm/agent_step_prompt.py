"""
agent_step_prompt.py  (the agent loop's per-hop LLM call -- org-agnostic)

Unlike router_prompt.py (which picks ONE action, once), this is called
repeatedly by core/agent/loop.py. Each call sees the original question
plus everything gathered so far, and returns exactly one of:

  {"step": "search_object", "object_type": ..., "filter": {...}}
  {"step": "get_field", "object_type": ..., "object_id": ..., "field_name": ...}
  {"step": "finish"}

The schema describing available object types/fields is rendered into the
prompt dynamically from whatever `schema` dict is passed in -- no object
type names are hardcoded here, so this file works unchanged for any
deployment's ontology.

model, ollama_url, and timeout_seconds are all passed in by the caller
(ultimately traced back to a deployment's config.yaml) -- this file has
no hardcoded model name or URL, same principle as gateway.py taking
users/actions as arguments rather than importing them.

Same fail-closed principle as before: anything malformed or unrecognized
returns {"step": "finish"} rather than guessing, so the loop stops
cleanly instead of doing something uncertain.

Called by: core/agent/loop.py
"""

import json
import requests

FINISH_STEP = {"step": "finish"}


def _describe_schema(schema: dict) -> str:
    lines = []
    for object_type, definition in schema.items():
        id_field = definition["id_field"]
        searchable = [id_field]
        link_only = []
        field_descriptions = []

        for field_name, info in definition["fields"].items():
            if info["type"] == "link":
                field_descriptions.append(f"{field_name} (link -> {info['target']})")
                if info.get("cardinality") == "one":
                    searchable.append(field_name)
                else:
                    link_only.append(field_name)
            else:
                field_descriptions.append(f"{field_name} (data)")
                searchable.append(field_name)

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
        lines.append(block)
    return "\n".join(lines)


def _build_system_prompt(schema: dict) -> str:
    return f"""You gather information step by step to answer a question,
using ONLY these object types and fields:

{_describe_schema(schema)}

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


def next_step(query_text: str, schema: dict, gathered_so_far: list[dict],
              model: str, ollama_url: str, timeout_seconds: int = 180) -> dict:
    user_message = (
        f"Question: {query_text}\n\n"
        f"Gathered so far: {json.dumps(gathered_so_far)}\n\n"
        f"What is the next step?"
    )

    try:
        response = requests.post(
            ollama_url,
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _build_system_prompt(schema)},
                    {"role": "user", "content": user_message},
                ],
                "format": "json",
                "options": {"temperature": 0},
                "stream": False,
            },
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        raw_content = response.json()["message"]["content"]
        parsed = json.loads(raw_content)
    except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
        print(f"[agent_step_prompt] request/parse failed, finishing: {e}")
        return FINISH_STEP

    step = parsed.get("step")

    if step == "finish":
        return FINISH_STEP

    if step == "search_object":
        if "object_type" not in parsed or "filter" not in parsed:
            print("[agent_step_prompt] malformed search_object step, finishing")
            return FINISH_STEP
        return {"step": "search_object", "object_type": parsed["object_type"], "filter": parsed["filter"]}

    if step == "get_field":
        required = {"object_type", "object_id", "field_name"}
        if not required.issubset(parsed.keys()):
            print("[agent_step_prompt] malformed get_field step, finishing")
            return FINISH_STEP
        return {
            "step": "get_field",
            "object_type": parsed["object_type"],
            "object_id": parsed["object_id"],
            "field_name": parsed["field_name"],
        }

    print(f"[agent_step_prompt] unrecognized step {step!r}, finishing")
    return FINISH_STEP
