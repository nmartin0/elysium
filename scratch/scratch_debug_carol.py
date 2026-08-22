from core.agent.loop import run_agent_loop
from core.intermediate_layer.auth import get_user_region
from deployments.acme_corp.policy import USERS
from deployments.acme_corp.ontology_adapter import search_object, get_field
from deployments.acme_corp.ontology_schema import SCHEMA

user_region = get_user_region(USERS, "user_carol")
print(f"Carol's region: {user_region}")

gathered = run_agent_loop(
    user_region=user_region,
    query_text="What are cust_004's recent transactions?",
    schema=SCHEMA,
    search_fn=search_object,
    get_field_fn=get_field,
)

print("--- gathered ---")
for item in gathered:
    print(item)
