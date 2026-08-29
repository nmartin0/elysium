"""
schema.py  (generic schema introspection -- org-agnostic)

Given a deployment's own schema dict (loaded from
ontology_schema.yaml via core/deployment_loader.py),
answers questions about object types and fields: does this field exist,
is it a link or plain data, what does a link point to, and which field
is the object's identifier.

No SQL, no table names, no org-specific knowledge -- this file only
knows the SHAPE a schema dict must have. Pure, stateless functions on
purpose: core/ontology/mediator.py's DataMediator class holds the
schema as instance state and calls these; wrapping these in their own
class too would just be indirection with no real payoff.

Used by: core/ontology/mediator.py, and core/llm/agent_step_prompt.py
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
    # Single source of truth for this rule: both core/ontology/mediator.py
    # (deciding what a real query may filter by) and
    # core/llm/agent_step_prompt.py (deciding what to tell the LLM it may
    # search by) call this -- previously each computed the same rule
    # independently, which risked the two drifting out of sync.
    if field_info["type"] == "data":
        return True
    return field_info["type"] == "link" and field_info.get("cardinality") == "one"


def get_field_storage_name(field_info: dict) -> str | None:
    # MDO (multi-datasource object types) -- the named entry in this
    # type's additional_storage this field is backed by, or None if it
    # uses the type's own primary "storage" block (the default, and by
    # far the common case -- every field before MDO existed implicitly
    # worked this way). Pure lookup, no resolution -- see
    # DataMediator._resolve_shared_storage() for turning this name into
    # an actual adapter/table/id_column.
    return field_info.get("storage")


def get_field_column(field_info: dict, field_name: str) -> str:
    # The actual SQL column name backing this field -- itself, unless
    # overridden via an explicit "column" key. Needed because MDO
    # sources won't always happen to name their columns exactly like
    # our own field names (e.g. a "risk_score" field pulled from a
    # column actually called "score_value" in someone else's database)
    # -- see ontology_schema.yaml's own MDO comments for the full
    # reasoning. Every field before MDO existed implicitly used this
    # same field_name-equals-column-name default.
    return field_info.get("column", field_name)


def get_column_for_field(resolved_type_config: dict, field_name: str) -> str:
    # Resolves ANY field name -- including the type's own id_field,
    # which is NOT a regular entry in resolved_type_config["fields"]
    # at all (a separate, top-level schema key) -- to its real SQL
    # column name. The id_field's own column always comes from
    # resolved_type_config["storage"]["id_column"] directly, never
    # MDO-overridden -- an object's identity always lives on its
    # primary storage (see DataMediator._resolve_shared_storage()'s
    # own docstring). Every other field goes through get_field_column()
    # as before.
    #
    # A REAL, confirmed gap this closes: writing to a type's own
    # id_field (e.g. a named action's "create" mutations supplying the
    # new object's own ID) previously hit a raw KeyError the moment
    # any of write_mediator.py's four field-to-column call sites tried
    # resolved_type_config["fields"][id_field] -- caught directly while
    # testing a real "create" action end to end, not assumed.
    # DataMediator.search_object() already solved this EXACT problem
    # correctly, inline, for its own criteria-translation needs; this
    # extracts that same logic into one shared, reusable place instead
    # of leaving it duplicated (or re-solved slightly differently) at
    # every call site that needs it -- the same discipline already
    # applied to is_searchable_field() and evaluate_submission_criteria().
    #
    # resolved_type_config is expected to be the SYNTHETIC config
    # _resolve_shared_storage() returns ({**type_schema, "storage":
    # storage_block}) -- id_field is always present on it unchanged,
    # since MDO resolution only ever swaps "storage", never "id_field".
    id_field = resolved_type_config["id_field"]
    if field_name == id_field:
        return resolved_type_config["storage"]["id_column"]
    return get_field_column(resolved_type_config["fields"][field_name], field_name)
