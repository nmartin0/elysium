from core.agent.loop import run_agent_loop
from deployments.acme_corp.ontology_adapter import search_object, get_field
from deployments.acme_corp.ontology_schema import SCHEMA

# Deliberately simple: should only need search_object + one get_field,
# then finish. Only 2 real hops needed, well under max_hops.
query = "What region is cust_001 in?"

gathered = run_agent_loop(
    user_region="us-west",
    query_text=query,
    schema=SCHEMA,
    search_fn=search_object,
    get_field_fn=get_field,
)

print(f"Hops taken: {len(gathered)}")
for item in gathered:
    print(item)

if len(gathered) < 8:
    print("\n=> Stopped BEFORE hitting max_hops -- finish signal likely worked.")
else:
    print("\n=> Hit max_hops -- finish signal did NOT trigger, even on an easy question.")
