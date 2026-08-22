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

COMPLETENESS CHECK: similar idea, applied to finishing too early. When
the model tries to finish, this checks whether sibling objects of the
same type (e.g. two transactions) have uneven data gathered about them.
If so, it gets ONE corrective nudge before being allowed to finish for
real -- soft, not a hard rule, since some asymmetry is legitimate if a
question only needs certain fields for certain items.

INVALID STEP RECOVERY: same recoverable-mistake philosophy applied to
schema validation errors (e.g. requesting a field that doesn't exist on
that object type). Previously this ended the loop outright, discarding
everything gathered -- now it's treated the same as a duplicate: the
model sees exactly what was invalid and gets a capped number of retries
before the loop actually gives up.

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


def _detect_asymmetry(gathered: list[dict]) -> str | None:
    """Looks for uneven data gathered across sibling objects of the same
    type (e.g. two transactions where one has 3 fields fetched and the
    other has 1). Returns a description if found, else None. This is a
    soft signal, not a rule -- some asymmetry is legitimate if a
    question only needs certain fields for certain items."""
    fields_by_type_id: dict = {}
    for item in gathered:
        if item.get("step") != "get_field":
            continue
        result = item.get("result")
        if isinstance(result, list):
            continue  # this was a link fetch (a list of IDs), not a data field
        obj_type = item["object_type"]
        obj_id = item["object_id"]
        fields_by_type_id.setdefault(obj_type, {}).setdefault(obj_id, set()).add(item["field_name"])

    for obj_type, id_map in fields_by_type_id.items():
        if len(id_map) < 2:
            continue
        field_sets = [frozenset(f) for f in id_map.values()]
        if len(set(field_sets)) > 1:
            details = ", ".join(f"{oid}: {sorted(fields)}" for oid, fields in id_map.items())
            return f"Uneven data gathered across {obj_type} objects -- {details}."
    return None


def run_agent_loop(user_region: str, query_text: str, schema: dict,
                    search_fn, get_field_fn,
                    model: str, ollama_url: str, timeout_seconds: int = 180,
                    max_hops: int = 8,
                    max_consecutive_duplicates: int = 2,
                    max_consecutive_invalid_steps: int = 2) -> list[dict]:
    gathered = []
    seen_signatures = set()
    consecutive_duplicates = 0
    consecutive_invalid = 0
    asymmetry_nudged = False

    for hop_count in range(1, max_hops + 1):
        step = next_step(query_text, schema, gathered, model, ollama_url, timeout_seconds)

        if step["step"] == "finish":
            if not asymmetry_nudged:
                asymmetry = _detect_asymmetry(gathered)
                if asymmetry:
                    print(f"[agent loop] asymmetry detected at finish, one nudge: {asymmetry}")
                    asymmetry_nudged = True
                    gathered.append({
                        "step": "completeness_check",
                        "note": f"{asymmetry} If this gap matters for the "
                                f"question, fill it in; otherwise finish is fine.",
                    })
                    continue
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
            consecutive_invalid = 0
        except ValueError as e:
            consecutive_invalid += 1
            print(f"[agent loop] invalid step ({consecutive_invalid}/"
                  f"{max_consecutive_invalid_steps}): {step} -- {e}")

            if consecutive_invalid >= max_consecutive_invalid_steps:
                print("[agent loop] too many consecutive invalid steps, stopping")
                break

            # Same recoverable-mistake treatment as duplicates: tell the
            # model exactly what was wrong and let it try something else,
            # rather than discarding everything gathered so far.
            gathered.append({
                "step": "rejected_invalid_step",
                "note": f"That step was invalid: {step} -- {e}. "
                        f"Check the schema above and try something valid, "
                        f"or finish if you have enough already.",
            })
    else:
        print(f"[agent loop] hit max_hops ({max_hops}), stopping")

    return gathered
