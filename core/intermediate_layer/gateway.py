"""
gateway.py  (the orchestrator -- generic, no org data)

Every action passes through here, in this fixed order:
    1. auth.authorize(users, user_id, action_id)     -- allowed or denied?
    2. audit.log_pre(...)                              -- log intent BEFORE running it
    3. action_registry.dispatch(actions, ...)            -- run the matching adapter
    4. audit.log_post(...)                                -- log what was returned

If step 1 denies, steps 3-4's dispatch never runs.

`users` and `actions` are passed in by the caller -- this file has no
idea which org it's serving, on purpose.

STALE, PENDING REDESIGN (same as action_registry.py): built for the old
flat action-dispatch model, before AgentLoop existed. Two known gaps a
real reconnection needs to resolve, not just patch:
  - record_ids extraction below has no generic way to know a result's
    ID field -- that concept (id_field) didn't exist until the ontology
    schema was built. AgentLoop's own per-field logging would need to
    replace this, not reuse it as-is.
  - This whole request/response shape (one action_id + params in, one
    records list out) doesn't match AgentLoop.run()'s multi-hop
    traversal at all.

Called by: NOTHING right now -- this is the honest current state, not
           aspirational. deployments/<org>/test_run.py uses AgentLoop
           directly instead (see core/agent/agentic_loop.py's KNOWN GAP note).
           This function is complete and correct on its own, waiting
           to be wired back in once the two gaps above are resolved.
"""

from core.intermediate_layer import auth, audit, action_registry


def handle_request(users: dict, actions: dict, security_attribute: str,
                    request_id: str, user_id: str, query_text: str,
                    action_id: str, params: dict) -> dict:
    decision = auth.authorize(users, user_id, action_id)

    audit.log_pre(request_id, user_id, query_text, action_id, params, decision)

    if not decision:
        return {"status": "denied", "records": []}

    user_security_value = auth.get_user_security_value(users, user_id, security_attribute)
    records = action_registry.dispatch(actions, action_id, user_security_value, params)

    # No generic way to know each record's real ID field at this layer
    # (see module docstring) -- but the audit trail must still show an
    # ACCURATE count of what was disclosed. Passing an empty list here
    # would make audit.log_post() always report 0, silently undercounting
    # every disclosure -- worse than having no IDs at all. Placeholders
    # sized to match keep the count honest even without real identifiers.
    audit.log_post(request_id, "success", [None] * len(records))

    return {"status": "success", "records": records}
