"""
gateway.py  (the orchestrator -- generic, no org data)

Every action passes through here, in this fixed order:

    1. auth.authorize(users, user_id, action_id)     -- allowed or denied?
    2. audit.log_pre(...)                              -- log intent BEFORE running it
    3. action_registry.dispatch(actions, ...)            -- run the matching adapter
    4. audit.log_post(...)                                -- log what was returned

If step 1 denies, steps 3-4's dispatch never runs.

`users` and `actions` are passed in by the caller (a specific deployment's
test_run.py or, later, whatever wraps the agentic loop) -- this file has
no idea which org it's serving, on purpose.

Called by: deployments/<org>/test_run.py (for now)
"""

from core.intermediate_layer import auth, audit, action_registry


def handle_request(users: dict, actions: dict, request_id: str, user_id: str,
                    query_text: str, action_id: str, params: dict) -> dict:
    decision = auth.authorize(users, user_id, action_id)

    audit.log_pre(request_id, user_id, query_text, action_id, params, decision)

    if not decision:
        return {"status": "denied", "records": []}

    user_region = auth.get_user_region(users, user_id)
    records = action_registry.dispatch(actions, action_id, user_region, params)

    record_ids = [r.get("transaction_id") for r in records]
    audit.log_post(request_id, "success", record_ids)

    return {"status": "success", "records": records}
