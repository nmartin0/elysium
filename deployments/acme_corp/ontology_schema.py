"""
ontology_schema.py  (acme_corp-specific -- NOT portable to other orgs)

Describes the object types this deployment exposes, their identifying
field, and their other fields -- pure data, no query logic. Each field
is either "data" (a plain value) or "link" (its value is another
object's ID, pointing at "target").

id_field tells the ontology layer (and the agent, via the prompt) which
field to use when calling search_object() -- without this, nothing
distinguishes an object's identifier from its other fields.

Used by: core/ontology/ (schema introspection)
         core/llm/agent_step_prompt.py (renders this into the agent's prompt)
         deployments/acme_corp/ontology_adapter.py (actual query logic)
"""

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "fields": {
            "region":       {"type": "data"},
            "name":         {"type": "data"},
            "email":        {"type": "data"},
            "transactions": {"type": "link", "target": "Transaction", "cardinality": "many"},
        },
    },
    "Transaction": {
        "id_field": "transaction_id",
        "fields": {
            "amount":           {"type": "data"},
            "currency":         {"type": "data"},
            "category":         {"type": "data"},
            "transaction_date": {"type": "data"},
            "customer_id":      {"type": "link", "target": "Customer", "cardinality": "one"},
        },
    },
}
