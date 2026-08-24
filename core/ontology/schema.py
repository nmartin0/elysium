"""
schema.py  (generic schema introspection -- org-agnostic)

Given a deployment's own schema dict (loaded from
deployments/<org>/ontology_schema.yaml via core/deployment_loader.py),
answers questions about object types and fields: does this field exist,
is it a link or plain data, what does a link point to, and which field
is the object's identifier.

No SQL, no table names, no acme_corp knowledge -- this file only knows
the SHAPE a schema dict must have. Pure, stateless functions on purpose:
core/ontology/sql_adapter.py's OntologyEngine class holds the schema as
instance state and calls these; wrapping these in their own class too
would just be indirection with no real payoff.

Used by: core/ontology/sql_adapter.py, and core/llm/agent_step_prompt.py
         (specifically is_searchable_field() -- see its own docstring)
"""


def get_id_field(schema: dict, object_type: str) -> str:
    # Which field name is this object type's identifier (e.g. "customer_id").
    type_schema = schema.get(object_type)
    if type_schema is None:
        raise ValueError(f"Unknown object_type: {object_type}")
    return type_schema["id_field"]


def get_field_info(schema: dict, object_type: str, field_name: str) -> dict:
    # The raw field descriptor dict for one field -- callers use this to
    # check its type, target, cardinality, etc. via the helpers below.
    type_schema = schema.get(object_type)
    if type_schema is None:
        raise ValueError(f"Unknown object_type: {object_type}")

    field_info = type_schema["fields"].get(field_name)
    if field_info is None:
        raise ValueError(f"Unknown field {field_name!r} on {object_type!r}")

    return field_info


def is_link_field(field_info: dict) -> bool:
    # True if this field's value points to ANOTHER object, rather than
    # holding data directly (e.g. "customer_id" on a Transaction).
    return field_info["type"] == "link"


def get_link_target(field_info: dict) -> str:
    # Which object type a link field points to (e.g. "Customer").
    return field_info["target"]


def is_searchable_field(field_info: dict) -> bool:
    # A field can be used as a search_object() filter key if it's plain
    # data, OR a forward link (cardinality "one" -- a real column on this
    # object's own table). A reverse link (cardinality "many") is NOT
    # searchable -- it's a computed relationship, not a real column.
    #
    # Single source of truth for this rule: both core/ontology/sql_adapter.py
    # (deciding what a real SQL query may filter by) and
    # core/llm/agent_step_prompt.py (deciding what to tell the LLM it may
    # search by) call this -- previously each computed the same rule
    # independently, which risked the two drifting out of sync.
    if field_info["type"] == "data":
        return True
    return field_info["type"] == "link" and field_info.get("cardinality") == "one"
