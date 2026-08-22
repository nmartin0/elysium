"""
ontology_schema.py  (acme_corp-specific -- NOT portable to other orgs)

Describes the object types this deployment exposes and their fields --
pure data, no query logic. Each field is either "data" (a plain value)
or "link" (its value is another object's ID, pointing at "target").

This is what makes get_field() generic: the ontology layer doesn't need
to know in advance which fields are links -- it looks it up here.

Used by: core/ontology/ (schema introspection)
         deployments/acme_corp/ontology_adapter.py (actual query logic)
"""

SCHEMA = {
    "Customer": {
        "fields": {
            "region":       {"type": "data"},
            "name":         {"type": "data"},
            "email":        {"type": "data"},
            "transactions": {"type": "link", "target": "Transaction", "cardinality": "many"},
        },
    },
    "Transaction": {
        "fields": {
            "amount":           {"type": "data"},
            "currency":         {"type": "data"},
            "category":         {"type": "data"},
            "transaction_date": {"type": "data"},
            "customer_id":      {"type": "link", "target": "Customer", "cardinality": "one"},
        },
    },
}
