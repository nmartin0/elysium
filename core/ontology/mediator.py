"""
mediator.py  (the data-silo router + security enforcer -- generic, org-agnostic)

Takes user_id directly now (not a pre-resolved security value) --
DataMediator holds users/roles/security_attribute itself and resolves
everything it needs internally via check_access(), the single canonical
enforcement point (see core/intermediate_layer/access_control.py).
Callers no longer need to separately resolve a security value before
calling in; the whole system is user_id-based end to end.

TWO gates enforced on EVERY object touched, per hop -- not once at the
start of a query:
  1. MAC (region/org boundary) -- _security_allowed(), re-derived live,
     never trusted from anywhere else.
  2. RBAC (role -> allowed_actions) -- via check_access(), action
     convention "read:{object_type}".
Both logged, allow or deny, via audit.log_access() -- this is what
makes RBAC enforcement on reads actually auditable, not just present.

Replaces the old OntologyEngine (pre-adapter-split) and, before that,
had NO RBAC at all -- only the MAC check. Extending RBAC to reads was a
deliberate decision made explicitly, not a silent default, because it's
a real behavior change: a user with no role, or a role missing the
right allowed_actions entry, now gets nothing back from ANY read, where
previously only the region check gated access.

CONCURRENCY -- two genuinely different mechanisms, not one:
  1. Per-object lock (_lock_for_object(), below) -- the PRIMARY
     correctness mechanism. Prevents lost updates: two writers to the
     SAME object serialize; two writers to DIFFERENT objects proceed
     fully concurrently, unaffected by each other. This is what
     actually protects data correctness.
  2. Adapter-declared write semaphore (via core.concurrency.
     ConcurrencyLimiter, built from adapter.max_concurrent_writes) --
     a narrow, honestly-declared EXCEPTION for backends with a real
     capacity constraint coarser than per-object (SQLite's whole-file
     write lock is the concrete example). Most adapters declare None
     here and never need this second mechanism at all.
A semaphore alone was an earlier, incorrect design -- it only ever
addressed capacity, never correctness (throttling WHEN writes run does
nothing about a write acting on data that went stale in between). See
core/concurrency.py's docstring for the full reasoning.

Used by: scripts/run_deployment.py (via core/deployment_loader.py),
         core/ontology/write_mediator.py, core/memory/guard.py
"""

import threading
from typing import Any

from core.concurrency import ConcurrencyLimiter, KeyedLockManager
from core.intermediate_layer.access_control import check_access
from core.ontology.interface import DataSiloAdapter
from core.ontology.schema import get_field_info, is_link_field, get_link_target, is_searchable_field


class DataMediator:
    def __init__(self, schema: dict, adapters: dict[str, DataSiloAdapter], silo_for_type: dict[str, str],
                 users: dict, roles: dict, security_attribute: str):
        # schema: the full ontology schema (object types/fields/security).
        # adapters: silo NAME -> adapter instance (e.g. "primary_sql" -> SQLiteAdapter(...)).
        # silo_for_type: object TYPE -> silo name (e.g. "Customer" -> "primary_sql").
        # users/roles/security_attribute: everything check_access() needs
        # to enforce MAC+RBAC on every read this mediator ever performs.
        self.schema = schema
        self.adapters = adapters
        self.silo_for_type = silo_for_type
        self.users = users
        self.roles = roles
        self.security_attribute = security_attribute

        # One semaphore per adapter, built from its declared capacity --
        # None means genuinely unlimited (most adapters), a real number
        # is the honest exception (SQLite's whole-file write lock).
        self._write_limiters = {
            silo_name: ConcurrencyLimiter(adapter.max_concurrent_writes)
            for silo_name, adapter in adapters.items()
        }

        # Per-object locks -- KeyedLockManager (core/concurrency.py)
        # uses dict.setdefault(), atomic per Python's own thread-safety
        # docs, so no separate guard lock is needed here.
        self._object_locks = KeyedLockManager()

    def _lock_for_object(self, object_type: str, object_id: Any) -> threading.Lock:
        return self._object_locks.lock_for((object_type, object_id))

    def _write_limiter_for(self, object_type: str) -> ConcurrencyLimiter:
        silo_name = self.silo_for_type[object_type]
        return self._write_limiters[silo_name]

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
        # PURE MAC mechanics only -- no RBAC, no audit logging here; this
        # is a low-level helper check_access() calls, not a public entry
        # point of its own.
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
        # The MAC check specifically -- called by check_access(), not
        # meant to be called directly by anything outside this module
        # and core/intermediate_layer/access_control.py.
        security_value = self._get_security_value(object_type, object_id)
        return security_value is not None and security_value == requesting_user_security_value

    def _filterable_columns(self, object_type: str) -> set:
        type_schema = self._type_schema(object_type)
        columns = {type_schema["id_field"]}
        for field_name, field_info in type_schema["fields"].items():
            if is_searchable_field(field_info):
                columns.add(field_name)
        return columns

    def search_object(self, user_id: str, object_type: str, criteria: dict) -> list:
        # Finds object(s) of one type matching search criteria, returns
        # only their IDs -- and only the ones check_access() (MAC+RBAC,
        # audited) allows for this user.
        type_schema = self._type_schema(object_type)

        valid_columns = self._filterable_columns(object_type)
        for key in criteria:
            if key not in valid_columns:
                raise ValueError(
                    f"Cannot filter {object_type} by {key!r} (valid: {sorted(valid_columns)})"
                )

        adapter = self._adapter_for(object_type)
        candidate_ids = adapter.find_ids(object_type, criteria, type_schema)
        action = f"read:{object_type}"

        return [
            candidate_id for candidate_id in candidate_ids
            if check_access(self, self.users, self.roles, self.security_attribute,
                             user_id, object_type, candidate_id, action)
        ]

    def get_field(self, user_id: str, object_type: str, object_id: Any, field_name: str):
        # Returns one field's value. If it's a link field, the value is
        # another object's ID (or list of IDs for a reverse link).
        field_info = get_field_info(self.schema, object_type, field_name)
        type_schema = self._type_schema(object_type)
        action = f"read:{object_type}"

        if not check_access(self, self.users, self.roles, self.security_attribute,
                             user_id, object_type, object_id, action):
            return None

        adapter = self._adapter_for(object_type)

        if is_link_field(field_info) and field_info.get("cardinality") == "many":
            target_type = get_link_target(field_info)
            self._assert_same_silo(object_type, target_type, "Reverse link")
            target_id_column = self.schema[target_type]["id_column"]
            return adapter.resolve_reverse_link(object_id, field_info, target_id_column)

        return adapter.get_raw_field(object_type, object_id, field_name, type_schema)
