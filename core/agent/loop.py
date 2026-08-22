"""
loop.py  (the agentic loop -- org-agnostic)

Repeatedly calls core/llm/agent_step_prompt.py to decide the next step
(search_object, get_field, or finish), executes that step against
whatever search_fn/get_field_fn were handed in, and accumulates results
until the model signals "finish", asks for something it already has
(duplicate detection -- see below), or max_hops is reached.

DUPLICATE DETECTION: small models don't always reliably notice they
already have what they're asking for again, even when told to check.
Rather than depend entirely on the model getting that right, this loop
tracks a signature of every executed step; if the model's next choice
exactly matches one already done, that's treated as an implicit "out of
new ideas" signal and the loop stops -- same fail-safe philosophy as
everything else here: a mechanical backstop, not just an instruction.

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


def _step_signature(step: dict):
    if step["step"] == "search_object":
        return ("search_object", step["object_type"], frozenset(step["filter"].items()))
    if step["step"] == "get_field":
        return ("get_field", step["object_type"], step["object_id"], step["field_name"])
    return None


def run_agent_loop(user_region: str, query_text: str, schema: dict,
                    search_fn, get_field_fn, max_hops: int = 8,
                    max_consecutive_duplicates: int = 2) -> list[dict]:
    gathered = []
    seen_signatures = set()
    consecutive_duplicates = 0

    for hop_count in range(1, max_hops + 1):
        step = next_step(query_text, schema, gathered)

        if step["step"] == "finish":
            break

        signature = _step_signature(step)
        if signature in seen_signatures:
            consecutive_duplicates += 1
            print(f"[agent loop] duplicate step ({consecutive_duplicates}/"
                  f"{max_consecutive_duplicates}): {step}")

            if consecutive_duplicates >= max_consecutive_duplicates:
                print("[agent loop] too many consecutive duplicates, stopping")
                break

            # Give the model a corrective nudge instead of ending outright --
            # a duplicate means "confused", not "done". Visible in the next
            # gathered_so_far so the model sees its request was rejected.
            gathered.append({
                "step": "rejected_duplicate",
                "note": f"You already have this: {step}. Choose something "
                        f"different, or finish if you have enough.",
            })
            continue

        consecutive_duplicates = 0
        seen_signatures.add(signature)

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
