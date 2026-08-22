"""
router_prompt.py  (Call 1: the "router")

Calls a local Ollama model and asks it to translate a user's question
into ONE structured action from a fixed list. Ollama's "format": "json"
mode guarantees syntactically valid JSON comes back, but NOT that it
matches our expected shape -- so we validate that ourselves below.

This validation is a SANITY check, not a SECURITY check -- it exists so
a malformed or hallucinated action never even reaches the gateway. The
real enforcement (is this user allowed to do this) still happens in
core/intermediate_layer/auth.py, unchanged.

Fails CLOSED: any uncertainty (bad JSON, unknown action, missing params)
results in returning "no action" rather than guessing or passing through
something we're not sure about.

Feeds into: core/intermediate_layer/gateway.py
"""

import json
import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b"

# What we sanity-check LLM output against: action_id -> required param keys.
# This is NOT the deployment's actual action registry (that's org-specific,
# see deployments/acme_corp/ontology_adapter.py) -- it's only the shape the
# router itself needs to recognize while parsing a response.
KNOWN_ACTIONS = {
    "get_customer_transactions": {"customer_id"},
}

SYSTEM_PROMPT = """You translate user requests into a single JSON action.

The ONLY action available is:
  action_id: "get_customer_transactions"
  params: {"customer_id": "<a string like cust_001>"}

Respond with ONLY a JSON object, no other text, in this exact shape:
  {"action_id": "get_customer_transactions", "params": {"customer_id": "cust_001"}}

If the request doesn't match this action, respond with:
  {"action_id": null, "params": {}}
"""

NO_ACTION = {"action_id": None, "params": {}}


def route_query(user_id: str, query_text: str) -> dict:
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": query_text},
                ],
                "format": "json",
                "stream": False,
            },
            timeout=120,
        )
        response.raise_for_status()
        raw_content = response.json()["message"]["content"]
        parsed = json.loads(raw_content)
    except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
        print(f"[router_prompt] request/parse failed, failing closed: {e}")
        return NO_ACTION

    action_id = parsed.get("action_id")
    params = parsed.get("params", {})

    if action_id is None:
        return NO_ACTION

    if action_id not in KNOWN_ACTIONS:
        print(f"[router_prompt] unknown action_id from model, failing closed: {action_id!r}")
        return NO_ACTION

    required_keys = KNOWN_ACTIONS[action_id]
    if not required_keys.issubset(params.keys()):
        print(f"[router_prompt] missing required params for {action_id!r}, failing closed")
        return NO_ACTION

    return {"action_id": action_id, "params": params}
