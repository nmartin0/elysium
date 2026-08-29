"""
mediator.py  (the data-silo router + security enforcer -- generic, org-agnostic)

ARCHITECTURE, NAMED PRECISELY: this class implements the classic
mediator-wrapper pattern from federated-database research -- a
"mediator" holding the semantic schema and routing decisions, talking
to "wrapper" adapters (adapters/sqlite_adapter.py, and any future one)
that are purely physical and know nothing about routing. This is the
SAME family of architecture as virtual knowledge graphs / ontology-
based data access (e.g. the Ontop system): a schema layer resolved
LIVE against genuinely separate, un-copied data sources at query time,
not a materialized/indexed copy of them. Worth naming explicitly
because it's a meaningfully different mechanism from Palantir Foundry's
own Ontology, despite the shared "ontology" vocabulary for the schema
concepts themselves (object types, link types) -- Foundry's Ontology
is a heavily materialized, pre-indexed layer (a separate ingestion
pipeline copies source data in before anything is queried); this
system deliberately never copies anything, resolving every link live
against whichever silo actually holds it, every time.

Each object type's schema entry (ontology_schema.yaml) separates its
SEMANTIC shape (fields, security, links -- what core/ontology/schema.py's
helpers ever read) from its PHYSICAL backing (storage.silo/table/
id_column -- what ONLY the adapter layer and _build_silo_for_type()
ever read) via a dedicated "storage" sub-key, not flat sibling keys --
a human editing what a Customer IS never needs to also see or
understand SQL table names, and vice versa.

MDO (MULTI-DATASOURCE OBJECT TYPES): one object type's DIFFERENT
properties can each be backed by a genuinely different silo, matching
Palantir's own column-wise MDO concept -- see _resolve_shared_storage()
below for the full mechanism. A field opts in via its own "storage" key
naming an entry in the type's "additional_storage" block; a field with
no "storage" key uses the type's own primary "storage" block, exactly
as every field did before MDO existed -- fully backward compatible,
zero changes required to any single-silo object type. A field may also
declare "column" to override the actual SQL column name it maps to
(defaulting to the field name itself, again matching every field's
existing behavior before this) -- real external silos won't always
happen to name a column exactly like our own field name.

DELIBERATE V1 SCOPE BOUNDARY, worth stating explicitly: a single
search_object() filter, get_field() call, or write may only touch
fields from ONE storage at a time -- see _resolve_shared_storage()'s
own docstring for why (federated cross-silo intersection and cross-
database write atomicity are both real, unsolved problems, intentionally
left for later, separately-justified work). This mirrors Palantir's own
MDO scope choice: they support column-wise MDO but explicitly not the
row-wise case, handled through an entirely different mechanism instead
of generalizing one to cover both.

Takes a pre-resolved UserRecord, not a raw user_id -- DataMediator no
longer holds users/security_attribute at all (dropped entirely, a real
reduction in responsibility, not a relocation): resolving a user's
identity happens ONCE per request, in the caller (see core/
intermediate_layer/auth.py's resolve_user_record()), and this class
only ever USES that resolved record. This also means DataMediator
itself never needs to look anyone up.

THREE gates, all fully explicit -- nothing implied by anything else:
  1. MAC (region/org boundary) -- _security_allowed(), re-derived live
     from the OBJECT's own data on every call, never trusted from
     anywhere else.
  2. RBAC, object-type level -- "read:{object_type}". Governs DISCOVERY
     only (may this user search_object/find IDs of this type at all).
  3. RBAC, field level -- "read:{object_type}.{field_name}". Governs
     seeing ONE specific field's value. Required for EVERY field,
     including the object type's own id_field -- an identifier is
     USUALLY just an opaque reference, but isn't always (a
     PasswordReset keyed by its own reset_token has a genuinely
     sensitive identifier), so it gets no special exemption.

UNIFORM DENIAL, deliberately: search_object()/get_field() NEVER raise a
distinguishing error for "doesn't exist" vs "exists but not authorized"
-- both look identical to the caller (empty list / None).

visible_schema() is what core/llm/agent_step_prompt.py calls to build
the LLM's prompt -- and AgentLoop.run() computes it ONCE per request
and passes it into search_object() explicitly (the optional
visible_schema parameter below) so a multi-step traversal doesn't
recompute the same authorize()-for-every-field-and-type work on every
single search_object call within one request. A caller without an
already-computed one (a direct/test caller) still works correctly --
search_object() computes it itself if none is passed in.

Used by: scripts/run_deployment.py (via core/deployment_loader.py),
         core/llm/agent_step_prompt.py, core/ontology/write_mediator.py,
         core/memory/guard.py, core/agent/agentic_loop.py
"""

import threading
from typing import Any

from core.concurrency import ConcurrencyLimiter, KeyedLockManager
from core.intermediate_layer.access_control import check_access
from core.intermediate_layer.auth import authorize, UserRecord
from core.ontology.interface import DataSiloAdapter
from core.ontology.schema import (
    is_link_field, get_link_target, is_searchable_field,
    get_field_storage_name, get_field_column,
)


class DataMediator:
    def __init__(self, schema: dict, adapters: dict[str, DataSiloAdapter],
                 silo_for_type: dict[str, str], roles: dict):
        self.schema = schema
        self.adapters = adapters
        self.silo_for_type = silo_for_type
        self.roles = roles

        self._write_limiters = {
            silo_name: ConcurrencyLimiter(adapter.max_concurrent_writes)
            for silo_name, adapter in adapters.items()
        }
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

    def _resolve_shared_storage(self, object_type: str, field_names) -> tuple[DataSiloAdapter, dict]:
        # MDO (multi-datasource object types) -- resolves ONE adapter +
        # synthetic type_config shared by every field in field_names.
        # A field may declare its own "storage" (an entry in this
        # type's additional_storage), backing it from a genuinely
        # different silo than its type's own primary one -- see
        # ontology_schema.yaml's own MDO comments for the full design.
        #
        # DELIBERATE V1 SCOPE BOUNDARY: raises if field_names span more
        # than one storage. A single search filter, get_field call, or
        # write may only touch fields from ONE storage at a time --
        # multi-storage search (federated intersection across adapters)
        # and multi-storage writes (no atomicity guarantee across
        # separate databases) are real, unsolved problems, deliberately
        # left for later, separately-justified work rather than
        # silently attempted here. This mirrors Palantir's own MDO
        # scope choice -- they support column-wise MDO but explicitly
        # not the row-wise case, handling that through an entirely
        # different mechanism instead of trying to generalize one
        # mechanism to cover both.
        #
        # The type's own id_field ALWAYS resolves to the primary
        # storage, never an additional_storage entry -- MDO lets
        # DIFFERENT PROPERTIES live in different places, but there is
        # still exactly one identity for the object, and every
        # additional_storage entry's own id_column exists only to say
        # HOW to join on that shared identity value, not to redefine it.
        type_schema = self._type_schema(object_type)
        id_field = type_schema["id_field"]

        storage_names = set()
        for field_name in field_names:
            if field_name == id_field:
                storage_names.add(None)
            else:
                storage_names.add(get_field_storage_name(type_schema["fields"][field_name]))

        if not storage_names:
            # No fields specified at all (e.g. search_object() with an
            # empty criteria dict, "give me everything") -- the primary
            # storage is the only sensible default, since that's where
            # the type's own identity column lives.
            storage_names = {None}

        if len(storage_names) > 1:
            raise ValueError(
                f"{object_type}: cannot combine fields from multiple storages "
                f"in one operation -- {sorted(field_names)}"
            )

        storage_name = storage_names.pop()
        storage_block = (
            type_schema["storage"] if storage_name is None
            else type_schema["additional_storage"][storage_name]
        )
        adapter = self.adapters[storage_block["silo"]]
        # A synthetic type_config -- everything from the real one,
        # EXCEPT storage, which is swapped for whichever block this
        # specific set of fields actually resolved to. Adapters only
        # ever read type_config["storage"], never anything else in this
        # dict, so this is safe -- see adapters/sqlite_adapter.py.
        synthetic_type_config = {**type_schema, "storage": storage_block}
        return adapter, synthetic_type_config

    def _get_security_value(self, object_type: str, object_id: Any) -> Any:
        # Resolves the row-level security value for one object, following
        # a via_field link if this object type doesn't hold it directly.
        # PURE MAC mechanics -- a mechanical internal lookup core/ needs
        # to make ITS OWN decision, not something gated by the acting
        # user's own field-level permissions.
        #
        # A via_field link CAN legitimately cross into a different data
        # silo -- e.g. a PayrollRecord (silo B) whose security chain
        # inherits an Employee's (silo A) department. This just works:
        # the recursive call below re-resolves _adapter_for(target_type)
        # fresh, from that type's OWN silo declaration, exactly the same
        # as the top of THIS call did for object_type -- nothing here
        # assumes the target lives in the same database as the source.
        # Proven with a real cross-database test, not just reasoned
        # about -- see tests/unit/test_cross_silo_links.py.
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
            return self._get_security_value(target_type, linked_id)

        raise ValueError(f"No security resolution declared for object_type {object_type!r}")

    def _security_allowed(self, object_type: str, object_id: Any, requesting_user_security_value: str) -> bool:
        security_value = self._get_security_value(object_type, object_id)
        return security_value is not None and security_value == requesting_user_security_value

    def visible_schema(self, user_record: UserRecord) -> dict:
        # THE single source of truth for "what does this user get to
        # know exists." A type is included whenever read:{object_type}
        # is granted -- even with zero visible DATA fields (discovery-
        # only access is a real, legitimate state). id_field requires
        # its own explicit read:{object_type}.{id_field} grant, same as
        # any other field -- no special case.
        visible = {}
        for object_type, type_def in self.schema.items():
            if not authorize(user_record, self.roles, f"read:{object_type}"):
                continue

            visible_fields = {
                field_name: field_info
                for field_name, field_info in type_def["fields"].items()
                if authorize(user_record, self.roles, f"read:{object_type}.{field_name}")
            }

            id_field = type_def["id_field"]
            id_field_visible = authorize(user_record, self.roles, f"read:{object_type}.{id_field}")

            visible[object_type] = {
                **type_def,
                "fields": visible_fields,
                "id_field": id_field if id_field_visible else None,
            }
        return visible

    def _filterable_columns(self, object_type: str, visible_type_def: dict) -> set:
        columns = set()
        if visible_type_def["id_field"] is not None:
            columns.add(visible_type_def["id_field"])
        for field_name, field_info in visible_type_def["fields"].items():
            if is_searchable_field(field_info):
                columns.add(field_name)
        return columns

    def search_object(self, user_record: UserRecord, object_type: str, criteria: dict,
                       visible_schema: dict | None = None) -> list:
        # visible_schema is OPTIONAL -- pass the already-computed one
        # (AgentLoop.run() does, once per request) to avoid recomputing
        # it on every search_object call within one traversal. A direct
        # caller with no pre-computed schema still works correctly;
        # this just computes it itself in that case.
        #
        # NEVER raises for "doesn't exist" or "not authorized to
        # discover" -- both return an empty list, indistinguishable
        # from a real search that legitimately matched nothing.
        visible = visible_schema if visible_schema is not None else self.visible_schema(user_record)
        visible_type_def = visible.get(object_type)
        if visible_type_def is None:
            return []

        valid_columns = self._filterable_columns(object_type, visible_type_def)
        for key in criteria:
            if key not in valid_columns:
                # Generic, no field list -- revealing "valid: [...]"
                # here would hand back exactly the schema visible_schema()
                # just deliberately hid.
                raise ValueError("Invalid search criteria")

        real_type_schema = self._type_schema(object_type)  # adapter needs table/id_column, not the filtered view
        adapter, resolved_type_config = self._resolve_shared_storage(object_type, list(criteria.keys()))

        # Translates each criteria KEY (a field name) to its real SQL
        # column name -- itself, unless MDO overrides it via "column"
        # (see get_field_column()'s own docstring). The id_field is
        # handled separately: it isn't a regular entry in
        # type_schema["fields"] at all, its column is whatever the
        # RESOLVED storage calls its own id_column.
        id_field = real_type_schema["id_field"]
        translated_criteria = {}
        for key, value in criteria.items():
            if key == id_field:
                translated_criteria[resolved_type_config["storage"]["id_column"]] = value
            else:
                translated_criteria[get_field_column(real_type_schema["fields"][key], key)] = value

        candidate_ids = adapter.find_ids(object_type, translated_criteria, resolved_type_config)
        action = f"read:{object_type}"

        return [
            candidate_id for candidate_id in candidate_ids
            if check_access(self, user_record, self.roles, object_type, candidate_id, action)
        ]

    def get_field(self, user_record: UserRecord, object_type: str, object_id: Any, field_name: str):
        # NEVER raises for "field/type doesn't exist" or "not authorized"
        # -- both return None.
        if object_type not in self.schema:
            return None

        action = f"read:{object_type}.{field_name}"
        if not check_access(self, user_record, self.roles, object_type, object_id, action):
            return None

        type_schema = self._type_schema(object_type)
        field_info = type_schema["fields"].get(field_name)
        if field_info is None:
            return None

        if is_link_field(field_info) and field_info.get("cardinality") == "many":
            # A reverse link's via_table almost always physically lives
            # in the TARGET type's own database, not the source's --
            # it's typically the target's own table, holding a foreign
            # key back to the source. So this query must run against
            # the TARGET's adapter, not the source object's adapter --
            # querying the source's adapter here was a real bug (not
            # just an overcautious guard) until this fix: it would
            # raise "no such table" the moment source and target lived
            # in different silos, since the via_table simply doesn't
            # exist in the source's own database. Proven with a real
            # cross-database test -- see tests/unit/test_cross_silo_links.py.
            target_type = get_link_target(field_info)
            target_adapter = self._adapter_for(target_type)
            target_id_column = self.schema[target_type]["storage"]["id_column"]
            return target_adapter.resolve_reverse_link(object_id, field_info, target_id_column)

        adapter, resolved_type_config = self._resolve_shared_storage(object_type, [field_name])
        column = get_field_column(field_info, field_name)
        return adapter.get_raw_field(object_type, object_id, column, resolved_type_config)
