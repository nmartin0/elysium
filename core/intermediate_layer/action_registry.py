"""
action_registry.py  (the dispatch MECHANISM -- generic, no org data)

Given a deployment's own action map (action_id -> adapter function) and
a chosen action_id, calls the right function.

STALE, PENDING REDESIGN: this file predates core/ontology/sql_adapter.py
and core/agent/agentic_loop.py's AgentLoop. Its flat "one action_id maps to one
function taking a params dict" model doesn't match how the system
actually works now -- AgentLoop drives multi-hop search_object()/
get_field() calls through OntologyEngine, not single action dispatch.
Reconnecting core/intermediate_layer/ to the live path means redesigning
this, not just patching it -- that's real design work for the auth/audit
reconnection task, not something to do incidentally here.

Called by: gateway.py (after authorization succeeds), passed the calling
           deployment's own actions dict as an argument.
"""


def dispatch(actions: dict, action_id: str, user_security_value: str, params: dict) -> list[dict]:
    action_fn = actions.get(action_id)
    if action_fn is None:
        raise ValueError(f"Unknown action_id: {action_id}")
    return action_fn(user_security_value, **params)
