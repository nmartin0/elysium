from core.agent.loop import run_agent_loop
from deployments.acme_corp.ontology_adapter import search_object, get_field
from deployments.acme_corp.ontology_schema import SCHEMA

gathered = run_agent_loop(
    user_region="us-west",
    query_text="What are cust_001's recent transactions?",
    schema=SCHEMA,
    search_fn=search_object,
    get_field_fn=get_field,
)

print("--- gathered steps ---")
for item in gathered:
    print(item)
