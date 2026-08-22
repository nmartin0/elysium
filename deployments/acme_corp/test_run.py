"""
test_run.py  (wires everything together, end to end -- for acme_corp)

All config/schema/policy comes from deployment.py, which loaded it from
YAML -- this file just passes it explicitly into core/ functions. No
hardcoded model names, URLs, or hop limits live here anymore.

KNOWN GAP, still true: this path only enforces REGION (via
get_user_region + the per-hop checks inside ontology_adapter.py). It
does NOT check auth.authorize() at all, so user_carol -- who has an
empty allowed_actions list -- will still get real data back for
cust_004, since her region ("eu") matches. Reconnecting this loop to
core/intermediate_layer/gateway.py (auth + audit) is still a real task.

Run from the project root:
    python3 -m deployments.acme_corp.test_run
"""

from core.agent.loop import run_agent_loop
from core.llm.synthesis_prompt import synthesize_insight
from core.intermediate_layer.auth import get_user_region

from deployments.acme_corp import deployment
from deployments.acme_corp.ontology_adapter import search_object, get_field


def run_example(user_id: str, query_text: str) -> None:
    print(f"--- {query_text!r} (as {user_id}) ---")

    user_region = get_user_region(deployment.USERS, user_id)
    if user_region is None:
        print("Unknown user -- no region on record.\n")
        return

    gathered = run_agent_loop(
        user_region=user_region,
        query_text=query_text,
        schema=deployment.SCHEMA,
        search_fn=search_object,
        get_field_fn=get_field,
        model=deployment.STEP_MODEL,
        ollama_url=deployment.OLLAMA_URL,
        timeout_seconds=deployment.REQUEST_TIMEOUT_SECONDS,
        max_hops=deployment.MAX_HOPS,
        max_consecutive_duplicates=deployment.MAX_CONSECUTIVE_DUPLICATES,
    )

    # Process bookkeeping isn't real data -- keep it out of synthesis input.
    real_data = [
        item for item in gathered
        if item["step"] not in ("rejected_duplicate", "completeness_check", "rejected_invalid_step")
    ]

    insight = synthesize_insight(
        query_text, real_data,
        model=deployment.SYNTHESIS_MODEL,
        ollama_url=deployment.OLLAMA_URL,
        timeout_seconds=deployment.REQUEST_TIMEOUT_SECONDS,
    )
    print(insight)
    print()


if __name__ == "__main__":
    run_example("user_alice", "What are cust_001's recent transactions?")
    run_example("user_alice", "What are cust_003's recent transactions?")
    run_example("user_carol", "What are cust_004's recent transactions?")
