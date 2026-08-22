from core.llm.agent_step_prompt import next_step
from deployments.acme_corp.ontology_schema import SCHEMA

step = next_step(
    query_text="What are cust_001's recent transactions?",
    schema=SCHEMA,
    gathered_so_far=[],
)
print(step)
