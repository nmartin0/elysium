from core.agent.loop import run_agent_loop
from core.llm.synthesis_prompt import synthesize_insight
from deployments.acme_corp.ontology_adapter import search_object, get_field
from deployments.acme_corp.ontology_schema import SCHEMA

query = "What are cust_001's recent transactions?"

gathered = run_agent_loop(
    user_region="us-west",
    query_text=query,
    schema=SCHEMA,
    search_fn=search_object,
    get_field_fn=get_field,
)

# Only real data results go to synthesis -- process bookkeeping like
# rejected_duplicate entries are noise here, not data to answer from.
real_data = [item for item in gathered if item["step"] != "rejected_duplicate"]

print("--- gathered (all, including process bookkeeping) ---")
for item in gathered:
    print(item)

print()
print("--- synthesized answer ---")
print(synthesize_insight(query, real_data))
