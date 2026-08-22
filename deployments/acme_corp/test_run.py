"""
test_run.py  (wires everything together, end to end -- for acme_corp)

Now driven by the agent loop instead of a single hardcoded action.

KNOWN GAP, made concrete here: this path only enforces REGION (via
get_user_region + the per-hop checks inside ontology_adapter.py). It
does NOT check auth.authorize() at all, so user_carol -- who has an
empty allowed_actions set and was previously denied outright by the
gateway path -- will now successfully get real data back for cust_004,
since her region ("eu") matches. This is the flagged gap from earlier
becoming visible, not a new bug. Reconnecting this loop to
core/intermediate_layer/gateway.py (auth + audit) is still a real task.

Run from the project root:
    python3 -m deployments.acme_corp.test_run
"""

from core.agent.loop import run_agent_loop
from core.llm.synthesis_prompt import synthesize_insight
from core.intermediate_layer.auth import get_user_region

from deployments.acme_corp.policy import USERS
from deployments.acme_corp.ontology_adapter import search_object, get_field
from deployments.acme_corp.ontology_schema import SCHEMA


def run_example(user_id: str, query_text: str) -> None:
    print(f"--- {query_text!r} (as {user_id}) ---")

    user_region = get_user_region(USERS, user_id)
    if user_region is None:
        print("Unknown user -- no region on record.\n")
        return

    gathered = run_agent_loop(
        user_region=user_region,
        query_text=query_text,
        schema=SCHEMA,
        search_fn=search_object,
        get_field_fn=get_field,
    )

    # Process bookkeeping (e.g. rejected_duplicate) isn't real data --
    # keep it out of what synthesis sees.
    real_data = [item for item in gathered if item["step"] != "rejected_duplicate"]

    insight = synthesize_insight(query_text, real_data)
    print(insight)
    print()


if __name__ == "__main__":
    run_example("user_alice", "What are cust_001's recent transactions?")
    run_example("user_alice", "What are cust_003's recent transactions?")
    run_example("user_carol", "What are cust_004's recent transactions?")
