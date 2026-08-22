"""
schema.py  (generic schema introspection -- org-agnostic)

Given a deployment's own SCHEMA dict (e.g. deployments/acme_corp/
ontology_schema.py), answers questions about object types and fields:
does this field exist, is it a link or plain data, what does a link
point to, and which field is the object's identifier.

No SQL, no table names, no acme_corp knowledge -- this file only knows
the SHAPE a schema dict must have, the same principle as auth.py and
action_registry.py in core/intermediate_layer/.

Used by: core/llm/agent_step_prompt.py, deployments/<org>/ontology_adapter.py
"""


def get_id_field(schema: dict, object_type: str) -> str:
    obj = schema.get(object_type)
    if obj is None:
        raise ValueError(f"Unknown object_type: {object_type}")
    return obj["id_field"]


def get_field_info(schema: dict, object_type: str, field_name: str) -> dict:
    obj = schema.get(object_type)
    if obj is None:
        raise ValueError(f"Unknown object_type: {object_type}")

    field = obj["fields"].get(field_name)
    if field is None:
        raise ValueError(f"Unknown field {field_name!r} on {object_type!r}")

    return field


def is_link_field(field_info: dict) -> bool:
    return field_info["type"] == "link"


def get_link_target(field_info: dict) -> str:
    return field_info["target"]
