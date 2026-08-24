"""
mediator.py  (the data-silo router + security enforcer -- generic, org-agnostic)

DataMediator replaces core/ontology/sql_adapter.py's old OntologyEngine.
The critical difference: OntologyEngine held BOTH the generic security/
link-traversal logic AND the SQL-specific mechanics in one class. This
class holds ONLY the generic logic -- every actual fetch is delegated to
whichever DataSiloAdapter owns the object type in question, resolved via
silo_for_type (built from each object type's `silo:` key in
ontology_schema.yaml).

SECURITY LIVES HERE, STRUCTURALLY -- not by convention. Adapters only
ever receive a fetch call AFTER _security_allowed() has already passed;
they have no way to see data a check hasn't cleared, because core/
simply never asks them for it otherwise.

v1 SCOPE DECISION: cross-silo links are not supported. If a security
chain (via_field) or a data link would need to cross from one silo to
another, this fails loudly with a specific error rather than silently
querying the wrong adapter or producing a confusing downstream failure.
Revisit only with a real, specific need -- see design conversation.

Used by: scripts/run_deployment.py (via core/deployment_loader.py),
         core/ontology/write_mediator.py, core/memory/guard.py
"""

from typing import Any

from core.ontology.interface import DataSiloAdapter
from core.ontology.schema import get_field_info, is_link_field, get_link_target, is_searchable_field


class DataMediator:
    def __init__(self, schema: dict, adapters: dict[str, DataSiloAdapter], silo_for_type: dict[str, str]):
        # schema: the full ontology schema (object types/fields/security).
        # adapters: silo NAME -> adapter instance (e.g. "primary_sql" -> SQLiteAdapter(...)).
        # silo_for_type: object TYPE -> silo name (e.g. "Customer" -> "primary_sql").
        self.schema = schema
        self.adapters = adapters
        self.silo_for_type = silo_for_type

    def _adapter_for(self, object_type: str) -> DataSiloAdapter:
        silo_name = self.silo_for_type[object_type]
        return self.adapters[silo_name]

    def _type_schema(self, object_type: str) -> dict:
        type_schema = self.schema.get(object_type)
        if type_schema is None:
            raise ValueError(f"Unknown object_type: {object_type}")
        return type_schema

    def _assert_same_silo(self, object_type: str, target_type: str, context: str) -> None:
        # The v1 cross-silo guard, shared by both the security-chain and
        # link-traversal paths that could otherwise cross a silo boundary.
        if self.silo_for_type[object_type] != self.silo_for_type[target_type]:
            raise ValueError(
                f"{context} from {object_type!r} crosses into {target_type!r}, "
                f"which lives in a different data silo -- cross-silo "
                f"resolution isn't supported yet."
            )

    def _get_security_value(self, object_type: str, object_id: Any) -> Any:
        # Resolves the row-level security value for one object, following
        # a via_field link if this object type doesn't hold it directly.
        # Assumes security chains terminate (no circular via_field refs).
        type_schema = self._type_schema(object_type)
        security = type_schema["security"]
        adapter = self._adapter_for(object_type)

        if "field" in security:
            return adapter.get_raw_field(object_type, object_id, security["field"], type_schema)

        if "via_field" in security:
            via_field = security["via_field"]
            linked_id = adapter.get_raw_field(object_type, object_id, via_field, type_schema)
            if linked_id is None:
                return None

            target_type = type_schema["fields"][via_field]["target"]
            self._assert_same_silo(object_type, target_type, "Security chain")
            return self._get_security_value(target_type, linked_id)

        raise ValueError(f"No security resolution declared for object_type {object_type!r}")

    def _security_allowed(self, object_type: str, object_id: Any, requesting_user_security_value: str) -> bool:
        # The per-hop enforcement check. Re-run on every object touched --
        # by search_object() for every candidate, and by get_field() before
        # reading any field -- so a link hop can never bypass this boundary.
        security_value = self._get_security_value(object_type, object_id)
        return security_value is not None and security_value == requesting_user_security_value

    def _filterable_columns(self, object_type: str) -> set:
        type_schema = self._type_schema(object_type)
        columns = {type_schema["id_field"]}
        for field_name, field_info in type_schema["fields"].items():
            if is_searchable_field(field_info):
                columns.add(field_name)
        return columns

    def search_object(self, requesting_user_security_value: str, object_type: str, criteria: dict) -> list:
        # Finds object(s) of one type matching search criteria, returns
        # only their IDs -- and only the ones the requesting user is
        # allowed to see.
        type_schema = self._type_schema(object_type)

        valid_columns = self._filterable_columns(object_type)
        for key in criteria:
            if key not in valid_columns:
                raise ValueError(
                    f"Cannot filter {object_type} by {key!r} (valid: {sorted(valid_columns)})"
                )

        adapter = self._adapter_for(object_type)
        candidate_ids = adapter.find_ids(object_type, criteria, type_schema)

        return [
            candidate_id for candidate_id in candidate_ids
            if self._security_allowed(object_type, candidate_id, requesting_user_security_value)
        ]

    def get_field(self, requesting_user_security_value: str, object_type: str, object_id: Any, field_name: str):
        # Returns one field's value. If it's a link field, the value is
        # another object's ID (or list of IDs for a reverse link).
        field_info = get_field_info(self.schema, object_type, field_name)
        type_schema = self._type_schema(object_type)

        if not self._security_allowed(object_type, object_id, requesting_user_security_value):
            return None

        adapter = self._adapter_for(object_type)

        if is_link_field(field_info) and field_info.get("cardinality") == "many":
            target_type = get_link_target(field_info)
            self._assert_same_silo(object_type, target_type, "Reverse link")
            target_id_column = self.schema[target_type]["id_column"]
            return adapter.resolve_reverse_link(object_id, field_info, target_id_column)

        return adapter.get_raw_field(object_type, object_id, field_name, type_schema)
