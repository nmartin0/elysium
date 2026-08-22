"""
loop.py  (the agentic loop -- org-agnostic)

Repeatedly calls core/llm/agent_step_prompt.py to decide the next step
(search_object, get_field, or finish), executes that step against
whatever search_fn/get_field_fn were handed in, and accumulates results
until the model signals "finish" or max_hops is reached (whichever
comes first) -- the explicit-signal-plus-safety-cap design.

search_fn and get_field_fn are passed in by the caller (e.g. a specific
deployment's ontology_adapter.py functions) -- this file has no idea
which org's data it's touching, same principle as gateway.py.

KNOWN GAP (flagged deliberately, not an oversight): this loop does NOT
go through core/intermediate_layer/gateway.py, so auth.authorize() and
audit logging are bypassed here for now. Region scoping still holds --
that enforcement lives inside search_fn/get_field_fn themselves, not in
the gateway. Reconnecting this loop to auth/audit is a real task for
later, not automatic.

Called by: deployments/<org>/test_run.py (or whatever replaces it)
"""

from core.llm.agent_step_prompt import next_step


def run_agent_loop(user_region: str, query_text: str, schema: dict,
                    search_fn, get_field_fn, max_hops: int = 8) -> list[dict]:
    gathered = []

    for hop_count in range(1, max_hops + 1):
        step = next_step(query_text, schema, gathered)

        if step["step"] == "finish":
            break

        try:
            if step["step"] == "search_object":
                result = search_fn(user_region, step["object_type"], step["filter"])
            elif step["step"] == "get_field":
                result = get_field_fn(
                    user_region, step["object_type"], step["object_id"], step["field_name"]
                )
            else:
                break  # shouldn't happen -- agent_step_prompt already validates this

            gathered.append({**step, "result": result})
        except ValueError as e:
            print(f"[agent loop] step failed, stopping: {e}")
            break
    else:
        print(f"[agent loop] hit max_hops ({max_hops}), stopping")

    return gathered
