from core.llm.agent_step_prompt import next_step
from deployments.acme_corp.ontology_schema import SCHEMA

gathered_so_far = [
    {"step": "search_object", "object_type": "Customer",
     "filter": {"customer_id": "cust_001"}, "result": ["cust_001"]}
]

step = next_step(
    query_text="What are cust_001's recent transactions?",
    schema=SCHEMA,
    gathered_so_far=gathered_so_far,
)
print(step)
