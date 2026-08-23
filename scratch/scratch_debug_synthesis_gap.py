from core.agent.loop import run_agent_loop
from core.llm.synthesis_prompt import synthesize_insight
from core.intermediate_layer.auth import get_user_region

from deployments.acme_corp import deployment
from deployments.acme_corp.ontology_adapter import search_object, get_field

query = "What are cust_001's recent transactions?"
user_region = get_user_region(deployment.USERS, "user_alice")

gathered = run_agent_loop(
    user_region=user_region,
    query_text=query,
    schema=deployment.SCHEMA,
    search_fn=search_object,
    get_field_fn=get_field,
    model=deployment.STEP_MODEL,
    ollama_url=deployment.OLLAMA_URL,
    timeout_seconds=deployment.REQUEST_TIMEOUT_SECONDS,
    max_hops=deployment.MAX_HOPS,
    max_consecutive_duplicates=deployment.MAX_CONSECUTIVE_DUPLICATES,
)

print("--- FULL gathered (including bookkeeping) ---")
for item in gathered:
    print(item)

real_data = [
    item for item in gathered
    if item["step"] not in ("rejected_duplicate", "completeness_check", "rejected_invalid_step")
]

print()
print("--- real_data ACTUALLY SENT TO SYNTHESIS ---")
for i, item in enumerate(real_data, start=1):
    print(f"[R{i}] {item}")

print()
print("--- synthesized answer ---")
print(synthesize_insight(
    query, real_data,
    model=deployment.SYNTHESIS_MODEL,
    ollama_url=deployment.OLLAMA_URL,
    timeout_seconds=deployment.REQUEST_TIMEOUT_SECONDS,
))
