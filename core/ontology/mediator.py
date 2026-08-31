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
search_object() filter or get_field() call may only touch fields from
ONE storage at a time -- see _resolve_shared_storage()'s own docstring
for why (federated cross-silo intersection is a real, unsolved
problem, intentionally left for later, separately-justified work).
This mirrors Palantir's own MDO scope choice -- they support
column-wise MDO but explicitly not the row-wise case, handled through
an entirely different mechanism instead of generalizing one to cover
both.

Cross-database WRITE atomicity for an "update" is now solved, when
write_log is configured -- see core/ontology/write_log.py's
own module docstring for the full mechanism (verified directly against
Palantir Foundry's own actual approach, not assumed) and its still-real,
explicitly stated remaining scope boundaries (multi-storage "create,"
crash recovery, search_object() integration). READS still enforce the
single-storage boundary above unconditionally; only WRITES gained a
path around it.

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
-- both look identical to the caller (empty list / None). This is a
CALLER-FACING guarantee only -- internally, both methods additionally
log_unknown_reference() (core/intermediate_layer/audit.py) whenever a
name genuinely doesn't exist in the schema, alongside (never instead
of) the normal access-check log entry. A standard security pattern,
not a project-specific invention: fail uniformly to the requester,
log the real reason for an operator -- see audit.py's own docstring.

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
from contextlib import contextmanager
from typing import Any

from core.concurrency import ConcurrencyLimiter, KeyedLockManager
from core.intermediate_layer.access_control import check_access
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import UserRecord, authorize
from core.ontology.interface import DataSiloAdapter
from core.ontology.schema import (
    get_column_for_field,
    get_field_storage_name,
    get_link_target,
    is_link_field,
    is_searchable_field,
)
from core.ontology.write_log import WriteLog


class DataMediator:
    def __init__(self, schema: dict, adapters: dict[str, DataSiloAdapter],
                 silo_for_type: dict[str, str], roles: dict,
                 write_log: WriteLog | None = None,
                 audit_log: AuditLog | None = None):
        self.schema = schema
        self.adapters = adapters
        self.silo_for_type = silo_for_type
        self.roles = roles
        # Optional, defaulting to None -- plenty of legitimate
        # DataMediator constructions have nothing to do with writes at
        # all (a read-only deployment, or any test exercising only
        # reads). None means get_field() below never checks the log,
        # identical to this class's behavior before the log existed.
        # The SAME instance a caller passes to WriteMediator when one
        # IS constructed -- WriteMediator now reads self.mediator.write_log
        # directly rather than taking its own, separately-passed copy,
        # so there is only ever one WriteLog per deployment, not two
        # values that could accidentally drift apart.
        self.write_log = write_log
        # UNLIKE write_log above, this is NEVER None -- audit logging is
        # a core security requirement this project treats as always-on,
        # not an opt-in capability (see AuditLog's own module docstring
        # for the full reasoning, and why its class-level default path
        # is a deliberate, narrower exception to this project's usual
        # "no defaults for per-deployment stores" rule). A caller not
        # providing one still gets a real, working AuditLog, writing to
        # a sensible default location, rather than every method below
        # needing an "if audit_log is not None" guard the way write_log
        # genuinely does.
        self.audit_log = audit_log if audit_log is not None else AuditLog()

        self._write_limiters = {
            silo_name: ConcurrencyLimiter(adapter.max_concurrent_writes)
            for silo_name, adapter in adapters.items()
        }
        self._object_locks = KeyedLockManager()

    def _lock_for_object(self, object_type: str, object_id: Any) -> threading.Lock:
        return self._object_locks.lock_for((object_type, object_id))

    @contextmanager
    def _locks_for_objects(self, object_refs: list[tuple[str, Any]]):
        # Multi-object counterpart to _lock_for_object() above -- used
        # by WriteMediator.confirm_and_execute() when applying a batch
        # (see write_mediator.py's own docstring for the full
        # sub_writes/write_log_batches mechanism this supports).
        #
        # SORTED acquisition order, deliberately -- the standard,
        # well-known deadlock-avoidance technique: two concurrent
        # multi-object batches that happen to share some objects can
        # never deadlock against each other as long as EVERY caller
        # acquiring more than one lock at once uses this SAME canonical
        # order (breaks circular wait, one of the four Coffman
        # conditions). str(object_id) in the sort key for the same
        # reason WriteLog's own object_id columns are consistently
        # str()-converted -- comparing a mix of int and str ids directly
        # would raise in Python 3, not just behave surprisingly.
        #
        # NOT the same as the order sub_writes actually APPLY in --
        # deliberately. Apply order stays the batch's own declared LIST
        # order (referential correctness: a sub_write creating an
        # object must apply before another sub_write that references
        # it). Lock ACQUISITION order is sorted for deadlock avoidance
        # ONLY -- these are two genuinely different orderings serving
        # two different purposes; conflating them would be a real bug,
        # not just a style inconsistency.
        sorted_refs = sorted(object_refs, key=lambda ref: (ref[0], str(ref[1])))
        locks = [self._lock_for_object(object_type, object_id) for object_type, object_id in sorted_refs]
        acquired = []
        try:
            for lock in locks:
                lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    def _write_limiter_for_silo(self, silo_name: str) -> ConcurrencyLimiter:
        # Keyed directly by silo name, not object_type -- needed by
        # WriteMediator's own log-based apply paths (see
        # _apply_one_update() and _apply_one_create() in
        # write_mediator.py), which resolve a limiter PER STORAGE
        # GROUP. Resolving by object_type alone would always give back
        # the PRIMARY silo's limiter, the wrong one for a group writing
        # to a different (e.g. MDO additional_storage) silo -- a real
        # bug, caught directly by tracing the actual call chain, not
        # just reasoned about (see write_mediator.py's own comment on
        # this at its update-side fix).
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
        # than one storage. A single search filter or get_field call
        # may only touch fields from ONE storage at a time -- multi-
        # storage search (federated intersection across adapters) is a
        # real, unsolved problem, deliberately left for later,
        # separately-justified work rather than silently attempted
        # here. This mirrors Palantir's own MDO scope choice -- they
        # support column-wise MDO but explicitly not the row-wise
        # case, handling that through an entirely different mechanism
        # instead of trying to generalize one mechanism to cover both.
        #
        # WRITE callers (WriteMediator) work AROUND this guard now,
        # deliberately, rather than being subject to it directly --
        # see core/ontology/write_log.py's own module docstring for
        # the mechanism: an "update" whose mutations span multiple
        # storages resolves each storage's own fields through a
        # SEPARATE call to this same method (one field at a time, or
        # grouped by storage), so this guard is simply never invoked
        # with more than one storage's worth of fields in a single
        # write anymore. This function itself is completely unchanged
        # -- it's the CALLING pattern for writes that changed.
        #
        # The type's own id_field ALWAYS resolves to the primary
        # storage, never an additional_storage entry -- MDO lets
        # DIFFERENT PROPERTIES live in different places, but there is
        # still exactly one identity for the object, and every
        # additional_storage entry's own id_column exists only to say
        # HOW to join on that shared identity value, not to redefine it.
        type_schema = self._type_schema(object_type)
        id_field = type_schema["id_field"]

        storage_names: set[str | None] = set()
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
        #
        # ALSO goes through _resolve_shared_storage(), same as every
        # other field read in this file -- the security-bearing field
        # ITSELF can be MDO-backed (unusual, but not disallowed by the
        # schema format), and this method used to bypass MDO entirely,
        # always querying the type's PRIMARY adapter/table regardless
        # of where security["field"]/["via_field"] actually lived. A
        # real, confirmed bug (a raw OperationalError, "no such
        # column") until this fix -- caught directly, not just reasoned
        # about, before being fixed. See tests/unit/test_mdo.py's
        # security-field-is-itself-MDO test.
        type_schema = self._type_schema(object_type)
        security = type_schema["security"]

        if "field" in security:
            field_name = security["field"]
            adapter, resolved_type_config = self._resolve_shared_storage(object_type, [field_name])
            # Checks the write log FIRST, via the SAME shared
            # _read_field_with_log_check() get_field() and
            # search_object() already use -- a real, previously-missed
            # gap otherwise: for an object still mid-CREATE, nothing
            # exists in the real backend AT ALL yet (not just this one
            # field), so a direct adapter read would return None and
            # incorrectly deny access to the very user who is creating
            # it, even though the pending write's own security value
            # would have matched them correctly. Caught directly by a
            # real test, not assumed -- see
            # tests/unit/test_write_log_create.py's own
            # test_get_field_sees_pending_create_value.
            return self._read_field_with_log_check(object_type, object_id, field_name, adapter, resolved_type_config)

        if "via_field" in security:
            via_field = security["via_field"]
            adapter, resolved_type_config = self._resolve_shared_storage(object_type, [via_field])
            linked_id = self._read_field_with_log_check(
                object_type, object_id, via_field, adapter, resolved_type_config
            )
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

    def _read_field_with_log_check(self, object_type: str, object_id: Any, field_name: str,
                                    adapter: DataSiloAdapter, resolved_type_config: dict) -> Any:
        # THE shared "check the write log first, else the real adapter"
        # merge -- factored out of get_field() so search_object()'s
        # write-log reconciliation (_reconcile_search_with_pending_writes()
        # below) and write_mediator.py's own _read_current_state_for_
        # criteria() can reuse the EXACT same logic, rather than each
        # growing its own, possibly-diverging copy. Takes an ALREADY-
        # resolved adapter/resolved_type_config rather than resolving
        # them itself -- every caller already has these in hand from
        # its own _resolve_shared_storage() call, and re-resolving here
        # would be redundant, not safer.
        #
        # Uses get_column_for_field() (not get_field_column()) --
        # unlike get_field() itself, callers here may legitimately ask
        # about the type's own id_field (e.g. a search criterion
        # naming it), which get_field_column() alone cannot resolve
        # (see get_column_for_field()'s own docstring for why the
        # id_field needs its own handling). For every OTHER field the
        # two produce an identical result -- get_column_for_field()
        # delegates to get_field_column() for anything that isn't the
        # id_field -- so this is a behavior-preserving generalization,
        # not a divergence, for get_field()'s own existing use.
        if self.write_log is not None:
            pending_changes = self.write_log.get_pending_changes(object_type, object_id)
            if pending_changes is not None and field_name in pending_changes:
                return pending_changes[field_name]
        column = get_column_for_field(resolved_type_config, field_name)
        return adapter.get_raw_field(object_type, object_id, column, resolved_type_config)

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
            # Distinguishes, for auditing, TWO genuinely different
            # reasons this returns empty -- the object_type ITSELF
            # doesn't exist in the schema at all (log_unknown_reference,
            # a real, useful signal a model may be guessing at type
            # names), vs a real type this user simply never had
            # read:{object_type} granted for. The latter is a genuine,
            # meaningful RBAC decision, previously never logged at all
            # (there's no object_id yet at this point, so check_access()
            # -- which needs one -- is never reached for this specific
            # gate). Reuses log_access()'s existing shape directly
            # (object_id=None, mac_allowed=None -- MAC genuinely never
            # applies without a specific object) rather than inventing
            # a third log shape for what's still fundamentally the same
            # kind of access decision.
            if object_type not in self.schema:
                self.audit_log.log_unknown_reference(user_record.user_id, object_type)
            else:
                self.audit_log.log_access(user_record.user_id, object_type, None, f"read:{object_type}",
                                           mac_allowed=None, rbac_allowed=False)
            return []

        valid_columns = self._filterable_columns(object_type, visible_type_def)
        for key in criteria:
            if key not in valid_columns:
                # Generic, no field list -- revealing "valid: [...]"
                # here would hand back exactly the schema visible_schema()
                # just deliberately hid.
                raise ValueError("Invalid search criteria")

        adapter, resolved_type_config = self._resolve_shared_storage(object_type, list(criteria.keys()))

        # Translates each criteria KEY (a field name) to its real SQL
        # column name -- see get_column_for_field()'s own docstring for
        # why the id_field needs its own handling (it isn't a regular
        # entry in type_schema["fields"] at all).
        translated_criteria = {
            get_column_for_field(resolved_type_config, key): value
            for key, value in criteria.items()
        }

        candidate_ids = adapter.find_ids(object_type, translated_criteria, resolved_type_config)
        candidate_ids = self._reconcile_search_with_pending_writes(
            object_type, criteria, candidate_ids, adapter, resolved_type_config
        )
        action = f"read:{object_type}"

        return [
            candidate_id for candidate_id in candidate_ids
            if check_access(self, user_record, self.roles, object_type, candidate_id, action)
        ]

    def _reconcile_search_with_pending_writes(self, object_type: str, criteria: dict, candidate_ids: list,
                                               adapter: DataSiloAdapter, resolved_type_config: dict) -> list:
        # Closes the gap write_log.py's own module docstring used to
        # name explicitly: search_object() queries the REAL backend
        # directly (via adapter.find_ids() above), which for an object
        # with a still-pending write reflects whatever it held BEFORE
        # that write, not the INTENDED value the write log already
        # promises get_field() will show. Left alone, that means an
        # object mid-update could be MISSING from a search for its own
        # new, intended value (the real row doesn't match yet), or
        # WRONGLY included in a search for the old value it's about to
        # stop having (the real row still matches, transiently).
        #
        # Only ever runs when write_log is configured -- see
        # this class's own __init__ for why None means completely
        # unchanged, pre-log behavior, same as get_field()'s own guard.
        if self.write_log is None:
            return candidate_ids

        # Every entry system-wide, not scoped to this object_type --
        # deliberately simple for this first pass: write_log entries
        # are expected to be rare (the pending window is normally
        # brief) and get_all_pending_writes() has no object_type
        # filter today (built for both this caller and WriteMediator.
        # resume_pending_writes(), which genuinely needs every entry
        # regardless of type). A real, stated cost if this ever proves
        # too slow in practice, not a correctness concern -- worth a
        # type-scoped query later if it matters, not assumed to matter
        # now. get_all_pending_writes(), NOT the old, retired get_
        # pending_entries() -- this must see a NOT-YET-STARTED
        # sub-write's own pending intent too, not just an already-
        # mid-apply one; see write_log.py's own docstring for why a
        # genuine gap here would let a search miss or wrongly include
        # an object for exactly the torn-state reason this whole
        # reconciliation mechanism exists to prevent.
        relevant_entries = [
            entry for entry in self.write_log.get_all_pending_writes()
            if entry["object_type"] == object_type and set(entry["changes"]) & set(criteria)
        ]
        if not relevant_entries:
            return candidate_ids

        # Keyed by str(id), not the id itself -- a pending entry's own
        # object_id is ALWAYS a string (see write_log.py's own
        # get_all_pending_writes() docstring), but a real, native id
        # from adapter.find_ids() might not be (e.g. an integer id
        # column). A plain set().discard(entry_object_id) would then
        # silently fail to remove an existing INTEGER match, since "1"
        # != 1 -- keying by string form on both sides makes add/remove
        # correct regardless of the id column's real type. Existing candidates
        # keep their own, already-correctly-typed value; a genuinely
        # NEW match (see the loop below) gets its native type resolved
        # fresh from the adapter, so nothing returned from here is ever
        # a bare string standing in for what should be e.g. an int.
        result_by_str = {str(candidate_id): candidate_id for candidate_id in candidate_ids}
        for entry in relevant_entries:
            object_id = entry["object_id"]
            # Re-derives this object's FULL match against criteria from
            # scratch, field by field, merging the log's pending value
            # over the real backend's current one exactly the way
            # get_field() itself would (via the SAME shared
            # _read_field_with_log_check()) -- not just the fields THIS
            # entry happens to change, since criteria can span fields
            # the entry never touches at all, and those still need
            # their (unaffected, real) current value included in the
            # match.
            matches = all(
                self._read_field_with_log_check(
                    object_type, object_id, field_name, adapter, resolved_type_config
                ) == expected_value
                for field_name, expected_value in criteria.items()
            )
            if matches:
                # setdefault, not a plain assignment -- if this id was
                # ALREADY a candidate (with its real, native type from
                # adapter.find_ids() itself), preserve that type rather
                # than overwriting it with the log's own string form.
                # For a genuinely NEW match (not previously a candidate
                # at all), resolve the REAL, natively-typed id.
                if object_id not in result_by_str:
                    if entry["operation"] == "create":
                        # The "sticky note" -- a create's own log entry
                        # always has the id written down directly (an
                        # explicit id is REQUIRED for multi-storage
                        # create -- see WriteMediator.propose_action()'s
                        # own validation), so this works even if the
                        # row doesn't exist yet in whichever storage
                        # THIS search happens to be scoped to. Reading
                        # it off the real row instead (like the update
                        # branch below does) would come back None for
                        # exactly that reason during the pending window.
                        id_field = self._type_schema(object_type)["id_field"]
                        native_id = entry["changes"][id_field]
                    else:
                        # Ordinary update -- the object already exists
                        # in every storage, so get_raw_field() already
                        # relies on SQLite's own type coercion to match
                        # a string id against a differently-typed
                        # column (the SAME thing every get_field() call
                        # already depends on whenever a caller supplies
                        # a string object_id for an integer-keyed
                        # type), reusing an existing, already-relied-
                        # upon behavior, not introducing a new fragility.
                        id_column = resolved_type_config["storage"]["id_column"]
                        native_id = adapter.get_raw_field(object_type, object_id, id_column, resolved_type_config)
                    result_by_str[object_id] = native_id
            else:
                result_by_str.pop(object_id, None)
        return list(result_by_str.values())

    def get_field(self, user_record: UserRecord, object_type: str, object_id: Any, field_name: str):
        # NEVER raises for "field/type doesn't exist" or "not authorized"
        # -- both return None.
        if object_type not in self.schema:
            # Distinguishes, for auditing, a genuinely unknown
            # object_type from an ordinary RBAC/MAC denial -- see
            # log_unknown_reference()'s own docstring.
            self.audit_log.log_unknown_reference(user_record.user_id, object_type)
            return None

        action = f"read:{object_type}.{field_name}"
        access_allowed = check_access(self, user_record, self.roles, object_type, object_id, action)

        type_schema = self._type_schema(object_type)
        field_exists = field_name in type_schema["fields"]

        if not field_exists:
            # ALWAYS logged, regardless of what check_access() just
            # decided -- this is the fix for a real ordering bug found
            # while verifying this mechanism directly: a made-up field
            # name almost always makes check_access() itself return
            # False (no role grants a nonexistent action string), which
            # means an early "if not access_allowed: return None" here
            # would make this branch effectively unreachable in the
            # COMMON case -- exactly the case (a model guessing at a
            # field name) this logging exists to catch. Determining
            # field_exists independently, and logging it independently
            # of access_allowed, is what actually achieves that.
            self.audit_log.log_unknown_reference(user_record.user_id, object_type, field_name)

        if not access_allowed or not field_exists:
            return None

        field_info = type_schema["fields"][field_name]

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

        # Checks core/ontology/write_log.py's own store FIRST, before
        # ever reaching the real adapter -- if an update touching this
        # exact field is still mid-apply (see WriteMediator.
        # _apply_one_update()), this is what makes that in-flight
        # window invisible to a reader: they see the INTENDED value
        # immediately, never a state where some of the update's
        # storages already reflect it and others don't yet. Delegated
        # to _read_field_with_log_check() -- the SAME shared logic
        # search_object()'s own write-log reconciliation uses, see its
        # own docstring for the full reasoning.
        adapter, resolved_type_config = self._resolve_shared_storage(object_type, [field_name])
        return self._read_field_with_log_check(object_type, object_id, field_name, adapter, resolved_type_config)


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - _locks_for_objects() used to be exercised only with a single-
#   element object_refs list, then, later, a genuine 2-element list
#   but only ever single-threaded (synthetic fixtures, and TransferFunds,
#   both proving correct STRUCTURE -- the right locks acquired in the
#   right order -- never genuine multi-threaded contention). NOW
#   CLOSED: tests/unit/test_concurrency.py is the first genuine,
#   multi-threaded proof either this method or KeyedLockManager
#   (core/concurrency.py) has ever had -- real OS threads, real
#   contention, timeout-bounded joins so a genuine deadlock fails the
#   test instead of hanging the whole suite. Includes a deliberate
#   negative control (raw, unsorted lock acquisition, bypassing this
#   method's own sorting) proving the detection methodology itself
#   catches a real deadlock, not just passing tautologically -- and,
#   caught by actually running that negative control rather than
#   trusting it by construction, a real bug in the control itself: the
#   two intentionally-deadlocked threads need daemon=True, or they
#   silently prevent the whole Python process from ever exiting (
#   reproduced directly: a bare subprocess run hung past 30s without
#   it). See core/concurrency.py's own docstring -- untouched by this
#   work, but ALSO had zero test coverage until this same file closed
#   it for ConcurrencyLimiter too, found while auditing for the
#   locking-specific gap and cheap enough to close in the same pass.
# - Also caught during a self-review of this same work: three of
#   tests/unit/test_concurrency.py's own tests had near-identical
#   "spawn threads, track max concurrent holders" boilerplate --
#   extracted into that file's own _run_concurrently_tracking_max_
#   holders() helper, matching the SAME duplication discipline this
#   project already applies elsewhere.
#
# ON PALANTIR ALIGNMENT (asked directly by the user; verified via
# official docs, not assumed -- checked because this project's own
# earlier claims about Palantir's real architecture, made before this
# locking mechanism existed, deserved re-checking against the actual
# thing just built): _locks_for_objects()'s sorted-order MUTEX locking
# does NOT mechanically match Palantir's own approach. Palantir's real
# mechanism for concurrent Ontology edits is an ASYNCHRONOUS, OFFSET-
# TRACKED QUEUE (the Funnel service) -- "the Actions service sends a
# modification instruction to the Funnel service. This instruction is
# stored in a Funnel-managed queue that has offset tracking to support
# simultaneous user edits" (palantir.com/docs/foundry/object-edits/
# how-edits-applied). Nothing in that architecture ever holds a lock
# at all; concurrent edits are appended to a queue, and offset
# tracking gives readers a consistency guarantee without mutual
# exclusion. See write_log.py's own AI-notes for where this project
# already, explicitly chose a DIFFERENT mechanism (checking a durable
# log directly at read time) for the SAME guarantee, at Elysium's
# smaller, single-process scale -- a deliberate, previously-discussed
# trade-off, not something to revisit lightly.
#
# The sharper point, not written down anywhere until now: sorted-order
# lock ACQUISITION -- the deadlock-avoidance mechanism THIS file's own
# _locks_for_objects() needs -- is solving a problem that only exists
# BECAUSE this project chose lock-based mutual exclusion in the first
# place. A queue is inherently serial; there is no "thread A holds
# resource 1, wants resource 2; thread B holds resource 2, wants
# resource 1" scenario in an offset-tracked queue, because nothing is
# ever holding two things at once waiting on a third. This project's
# own deadlock-avoidance work (this file, tests/unit/test_
# concurrency.py) is real, correct, and worth having -- but it is NOT
# "how Palantir does it." It is the correctness cost of a genuinely
# different, simpler architecture this project chose deliberately, and
# should be described that way if this comparison ever comes up again.
