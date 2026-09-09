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
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

from core.concurrency import ConcurrencyLimiter, KeyedLockManager
from core.filters import FieldFilter, row_matches, validate_filter
from core.intermediate_layer.access_control import check_access
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import UserRecord, authorize
from core.ontology.interface import ExternalReadAdapter, ExternalWriteAdapter
from core.ontology.schema import (
    get_column_for_field,
    get_display_name,
    get_field_storage_name,
    get_link_target,
    get_plural_display_name,
    is_link_field,
    is_searchable_field,
)
from core.ontology.write_log import WriteLogReader
from core.request_context import RequestContext

_AGGREGATES: dict[str, Callable[[list], Any]] = {
    "count": len,
    "sum": sum,
    "avg": lambda values: sum(values) / len(values),
    "min": min,
    "max": max,
}


# Sentinel for "absent from the cache", distinct from a cached None --
# which is a real security value meaning the object has none.
_MISSING = object()


@dataclass(frozen=True)
class ReauthorizedConditions:
    """What survived re-authorization, and what did not.

    `disabled` holds FIELD NAMES, not conditions: the UI needs to say
    "the region filter is inactive", and the name is what it says.
    """

    runnable: list
    disabled: list[str]


class DataMediator:
    def __init__(self, schema: dict, adapters: dict[str, ExternalReadAdapter],
                 silo_for_type: dict[str, str], roles: dict,
                 write_log: WriteLogReader | None = None,
                 audit_log: AuditLog | None = None,
                 mirror_synced_at: str | None = None):
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
        # When reads come from the local mirror, this is the mirror's
        # own last-sync timestamp -- what makes the read-your-writes
        # overlay in _read_field_with_log_check() below bounded rather
        # than unbounded. None for a live deployment, which disables
        # the overlay entirely (the live adapter already reads the
        # real, current value).
        self.mirror_synced_at = mirror_synced_at
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

        # Built LAZILY, per-silo, inside _write_limiter_for_silo()
        # below -- NOT eagerly here. A real, necessary correction:
        # this used to build one limiter per adapter unconditionally,
        # reading adapter.max_concurrent_writes -- but a genuine
        # ExternalReadAdapter (this class's own real, normal case,
        # once DataMediator's own read path moves to a read-only
        # credential) has no such attribute at all -- only
        # ExternalWriteAdapter does. Building this eagerly, for EVERY
        # DataMediator regardless of whether anything ever calls
        # _write_limiter_for_silo() on it, would make constructing a
        # genuinely read-only DataMediator fail outright. Lazy
        # construction means this code path is only ever exercised by
        # the one, real caller that actually needs it -- WriteMediator's
        # own internal, write-capable _adapter_mediator (see that
        # class's own __init__ docstring) -- never by a real, ordinary,
        # read-only DataMediator instance at all.
        self._write_limiters: dict[str, ConcurrencyLimiter] = {}
        # Security-value caches, populated by _prefetch_security_values()
        # and read by _get_security_value(). Cleared at the start of every
        # prefetch rather than persisting across operations: a security
        # value that changed between requests must never be served stale.
        self._security_value_cache: dict[tuple, Any] = {}
        self._security_link_cache: dict[tuple, tuple] = {}
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
        assert len(set(sorted_refs)) == len(sorted_refs), (
            f"duplicate object in lock set {sorted_refs} -- "
            f"threading.Lock is not reentrant, this would self-deadlock"
        )
        # DEDUPLICATED BY LOCK, NOT BY KEY. Locks are striped onto a
        # bounded set, so two DISTINCT objects can share one --
        # verified directly: ('Customer', 'c1') and ('Customer',
        # 'c1940') map to the same lock. Acquiring it twice in one
        # write would self-deadlock, since threading.Lock is not
        # reentrant, and the assert above cannot see it because the
        # KEYS differ.
        #
        # Ordering is still by sorted key, so every caller acquires
        # the same locks in the same sequence and cannot deadlock
        # against another caller either.
        locks: list = []
        for object_type, object_id in sorted_refs:
            lock = self._lock_for_object(object_type, object_id)
            if lock not in locks:
                locks.append(lock)
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
        #
        # Built lazily, on first real use, not eagerly in __init__ --
        # see that method's own comment for why: this method (and
        # therefore max_concurrent_writes) is only ever genuinely
        # needed on a real, write-capable ExternalWriteAdapter, never
        # on a genuine, read-only ExternalReadAdapter, which has no
        # such attribute at all. The cast() below is real, deliberate
        # type-narrowing, not a way of hiding a genuine mismatch: this
        # method is ONLY ever called via WriteMediator's own internal,
        # write-capable _adapter_mediator (see that class's own
        # __init__ docstring) -- self.adapters there genuinely does
        # hold ExternalWriteAdapter instances at runtime (in practice,
        # concretely, adapters/sqlite_adapter.py's own SQLiteWriteAdapter),
        # even though self.adapters' own STATIC type stays
        # dict[str, ExternalReadAdapter] for every OTHER, real,
        # read-only DataMediator this class also serves.
        # setdefault(), not `if not in: create`. That shape is
        # check-then-act: two threads both see the silo missing, both
        # build a limiter, and one silently replaces the other -- so
        # they end up holding DIFFERENT limiters for the same silo and
        # each enforces max_concurrent_writes independently. The
        # configured ceiling on concurrent writes to a customer's
        # database is then exceeded, with nothing raised and nothing
        # logged.
        #
        # Proven by forcing the interleaving rather than hoping for it:
        # two limiter objects created, two handed out. dict.setdefault()
        # is atomic under the GIL, which is the same guarantee
        # KeyedLockManager already relies on (see core/concurrency.py,
        # where the claim is tested directly).
        #
        # The limiter is constructed unconditionally, so a redundant one
        # may be built and discarded under contention. That is cheap
        # and, unlike the race, harmless -- an unused ConcurrencyLimiter
        # holds nothing.
        adapter = cast(ExternalWriteAdapter, self.adapters[silo_name])
        return self._write_limiters.setdefault(
            silo_name, ConcurrencyLimiter(adapter.max_concurrent_writes)
        )

    def _adapter_for(self, object_type: str) -> ExternalReadAdapter:
        silo_name = self.silo_for_type[object_type]
        return self.adapters[silo_name]

    def _type_schema(self, object_type: str) -> dict:
        type_schema = self.schema.get(object_type)
        if type_schema is None:
            raise ValueError(f"Unknown object_type: {object_type}")
        return type_schema

    def _resolve_shared_storage(self, object_type: str, field_names) -> tuple[ExternalReadAdapter, dict]:
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
        # Cache first, populated by _prefetch_security_values() when a
        # caller is resolving many objects. A MISS falls through to the
        # per-object reads below unchanged, so correctness never depends
        # on the cache being warm -- it only ever makes the same answer
        # cheaper to reach.
        # A SINGLE .get() per cache, not `if key in cache: return
        # cache[key]`. That shape is a check-then-get, and another
        # request's prefetch clearing the cache between the two raises
        # KeyError -- proven by forcing the interleaving directly, since
        # the GIL makes it rare rather than impossible.
        #
        # _MISSING rather than None as the sentinel: None is a REAL
        # cached security value, meaning "this object has none and is
        # therefore visible to nobody". Treating it as a miss would send
        # every such object down the slow path forever, and worse,
        # would make a genuine None indistinguishable from an absent
        # entry.
        cache_key = (object_type, str(object_id))
        cached = self._security_value_cache.get(cache_key, _MISSING)
        if cached is not _MISSING:
            return cached
        link = self._security_link_cache.get(cache_key)
        if link is not None:
            target_type, linked_id = link
            if linked_id is None:
                return None
            return self._get_security_value(target_type, linked_id)

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

    def _without_deleted(self, object_type: str, object_ids: list) -> list:
        """Drops objects whose latest applied write is a delete.

        Read in BULK, one query for the whole candidate set rather than
        one per object -- the same discipline Point 9 applied to
        security resolution, and for the same reason: a per-object
        check here would reintroduce exactly the N+1 that was just
        removed.
        """
        if self.write_log is None or not object_ids:
            return object_ids
        deleted = self.write_log.deleted_object_ids(object_type)
        if not deleted:
            return object_ids
        return [object_id for object_id in object_ids if str(object_id) not in deleted]

    def _prefetch_security_values(self, object_type: str, object_ids: list) -> None:
        """Resolves the security value for many objects at once, into
        the per-request cache _get_security_value() already reads.

        THE MEASURED PROBLEM. check_access() resolves each object's
        security value individually, and a via_field chain adds a read
        per hop. Profiling an aggregate over 20,000 objects: 6.25s
        total, 6.10s of it in check_access(). search_object() on 2,004
        objects issued 4,021 SQL queries before this existed.

        THE SHAPE OF THE FIX. A security chain is a walk over object
        TYPES, not over objects: every Transaction resolves through
        Customer, so the whole set needs one read of Transaction's
        via_field and one read of Customer's security field --
        regardless of how many objects there are. This walks the chain
        level by level, reading each level in bulk, so cost scales with
        the DEPTH of the chain rather than the size of the set.

        Deliberately populates a cache rather than changing
        check_access()'s signature. Every authorization decision still
        goes through the exact same code path, per object, in the same
        order, with the same audit logging -- this only makes the reads
        it performs cheaper. A security check that took a different
        route when batched would be a genuinely different check, and
        that is not a risk worth taking for speed.

        Silently does nothing on any failure. This is a cache warmer:
        if a bulk read fails for any reason, every caller still gets
        the correct answer from the per-object path, just slower.
        """
        self._security_value_cache.clear()
        self._security_link_cache.clear()
        pending = {object_type: [str(object_id) for object_id in object_ids]}
        seen_types = set()

        while pending:
            current_type, ids = pending.popitem()
            if current_type in seen_types or not ids:
                continue
            seen_types.add(current_type)

            type_schema = self.schema.get(current_type)
            if type_schema is None:
                continue
            security = type_schema.get("security") or {}
            field_name = security.get("field") or security.get("via_field")
            if field_name is None:
                continue

            try:
                rows = self._read_field_for_ids(current_type, ids, field_name)
            except Exception:
                # See the docstring: a warmer that fails must not break
                # the read it was warming.
                return

            if "field" in security:
                for object_id, value in rows.items():
                    self._security_value_cache[(current_type, str(object_id))] = value
                continue

            # A via_field hop: remember which linked id each object
            # resolves through, then batch the NEXT level.
            target_type = type_schema["fields"][field_name]["target"]
            for object_id, linked_id in rows.items():
                self._security_link_cache[(current_type, str(object_id))] = (target_type, linked_id)
            next_ids = [str(linked) for linked in rows.values() if linked is not None]
            if next_ids:
                pending[target_type] = next_ids

    def _read_field_for_ids(self, object_type: str, object_ids: list, field_name: str) -> dict:
        """One field, many objects, one adapter call. No authorization
        of its own -- this is the read half of _prefetch_security_
        values(), and resolving a security value is precisely the step
        that decides authorization, so it cannot itself be gated on
        one."""
        adapter, resolved_type_config = self._resolve_shared_storage(object_type, [field_name])
        id_column = resolved_type_config["storage"]["id_column"]
        column = get_column_for_field(resolved_type_config, field_name)

        # Filtered IN THE ENGINE. This read every row of the table and
        # discarded the rest in Python; fetching three objects out of
        # 200,004 read all of them.
        rows = adapter.read_fields_for_ids(
            resolved_type_config["storage"]["table"], id_column,
            list(object_ids), [column], resolved_type_config,
        )
        return {row[id_column]: row[column] for row in rows}

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
                field_name: {
                    **field_info,
                    "display_name": get_display_name(field_info, field_name),
                    "visibility": field_info.get("visibility", "normal"),
                    "status": field_info.get("status", "active"),
                }
                for field_name, field_info in type_def["fields"].items()
                if authorize(user_record, self.roles, f"read:{object_type}.{field_name}")
            }

            id_field = type_def["id_field"]
            id_field_visible = authorize(user_record, self.roles, f"read:{object_type}.{id_field}")

            # title_field -- OPTIONAL, and RBAC-gated the exact same
            # way id_field already is above: a real, existing grant is
            # required for THIS specific field's own value before it's
            # ever surfaced as "the" display name for this type, even
            # though the field name itself is declared, schema-wide,
            # in ontology_schema.yaml (schema STRUCTURE is not the same
            # thing as a field's own VALUE being visible -- the same
            # distinction visible_schema() already draws for every
            # other field here). None (not the declared name) when the
            # caller can't actually see it -- the UI already treats
            # None/absent identically to "no title_field declared at
            # all," falling back to the raw id, never a broken or
            # partially-rendered label.
            title_field = type_def.get("title_field")
            title_field_visible = title_field is not None and authorize(
                user_record, self.roles, f"read:{object_type}.{title_field}"
            )

            # A REAL, CONFIRMED BUG, fixed here: this used to spread the
            # FULL type_def (`**type_def`) into the result, which meant
            # `storage`/`additional_storage`/`security` -- real,
            # internal infrastructure detail from ontology_schema.yaml
            # (which physical database, table, and column backs a
            # field) -- leaked out through this method's own return
            # value, completely unfiltered, to EVERY caller, including
            # the two real HTTP routes (GET /me/visible-schema, GET
            # /users/{username}/visible-schema) that return this dict
            # directly as an HTTP response body. Never intentional --
            # confirmed directly, not assumed, that NOTHING anywhere in
            # this codebase actually reads those three keys off a
            # visible_schema() result: not agentic_loop.py's own LLM
            # prompt-building path, not this file's own internal
            # search_object()/_filterable_columns() callers (which use
            # ONLY `fields`/`id_field` from a visible_type_def, and
            # resolve real storage separately, from self.schema
            # directly, never from this filtered view). This was pure,
            # unused bycatch of the old spread pattern, not a real
            # dependency anywhere -- safe to remove outright, not just
            # scope down. Only the three real, intentional, semantic
            # keys below are ever included now.
            visible[object_type] = {
                "fields": visible_fields,
                "id_field": id_field if id_field_visible else None,
                "title_field": title_field if title_field_visible else None,
                # Display metadata, resolved here rather than in the
                # route: it is a property of the ONTOLOGY, and every
                # consumer (HTTP, the agent's own prompt) should see
                # the same label for the same field. Always present --
                # humanize() supplies a readable fallback -- so a UI
                # never has to decide what to show when none is
                # declared.
                "display_name": get_display_name(type_def, object_type),
                "plural_display_name": get_plural_display_name(type_def, object_type),
                "description": type_def.get("description"),
                # UI rendering hints. Cosmetic, never security: see
                # _validate_ui_metadata() for why `hidden` fields are
                # still returned here.
                "group": type_def.get("group"),
                "icon": type_def.get("icon"),
                "color": type_def.get("color"),
                "status": type_def.get("status", "active"),
            }
        return visible

    def _read_field_with_log_check(self, object_type: str, object_id: Any, field_name: str,
                                    adapter: ExternalReadAdapter, resolved_type_config: dict) -> Any:
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
            # A deleted object is not visible in the ontology, matching
            # Foundry's own rule: when the latest edit is a delete the
            # object is hidden "regardless of whether any corresponding
            # row is in one of the data sources". Checked BEFORE any
            # masking or adapter read, so a deleted object never leaks
            # a value through either path.
            if self.write_log.is_deleted(object_type, object_id):
                return None

            pending_changes = self.write_log.get_pending_changes(object_type, object_id)
            if pending_changes is not None and field_name in pending_changes:
                return pending_changes[field_name]

            # THE MIRROR OVERLAY -- read-your-writes when reads come
            # from the local mirror rather than the live database. A
            # confirmed write is genuinely applied to the customer's
            # real database, but the mirror is a point-in-time copy
            # that hasn't been re-synced yet, so without this a person
            # would approve a change and not see it until the next
            # scheduled sync.
            #
            # Deliberately consulted AFTER pending_changes above, not
            # instead of it: the two answer different questions (an
            # in-flight write vs. an applied-but-not-yet-mirrored one),
            # and a still-pending write's INTENDED value should win
            # over an older applied one for the same object.
            #
            # mirror_synced_at is None for a live deployment, which
            # makes this a no-op there -- the live adapter already
            # reads the real, current value, so there is nothing to
            # overlay.
            applied = self.write_log.get_applied_changes_since(
                object_type, object_id, self.mirror_synced_at
            )
            if applied is not None and field_name in applied:
                return applied[field_name]

        column = get_column_for_field(resolved_type_config, field_name)
        return adapter.get_raw_field(object_type, object_id, column, resolved_type_config)

    def reauthorize_conditions(self, user_record: UserRecord, object_type: str,
                               conditions: list) -> "ReauthorizedConditions":
        """Re-checks a SAVED filter against the caller's current
        schema, and says what was dropped.

        A saved artifact is a request, never an authority. Between
        saving and reopening, the author may have lost read access to a
        field they filtered on -- or the opener may be a colleague the
        search was shared with, who never had it. Each condition is
        checked against the opener's OWN visible schema, and any it
        cannot read is disabled.

        DISABLED AND REPORTED, not dropped silently and not failed
        hard. Dropping silently is the worst option: the user sees more
        rows than the search promised and concludes their data changed.
        Failing hard is unhelpful when the rest of the search still
        works. And there is no disclosure risk in naming the field --
        the person opening the artifact can already see the condition
        written in it. We are explaining their own saved query, not
        revealing what they cannot see.

        Returns the runnable conditions and the names of the disabled
        ones, so the UI can say so rather than guess.
        """
        visible = self.visible_schema(user_record)
        visible_type_def = visible.get(object_type)
        if visible_type_def is None:
            # Cannot read the type at all: nothing is runnable, and
            # every condition is disabled for the same reason.
            return ReauthorizedConditions(
                runnable=[], disabled=[condition.field for condition in conditions]
            )

        readable = self._filterable_columns(object_type, visible_type_def)
        runnable = [c for c in conditions if c.field in readable]
        disabled = [c.field for c in conditions if c.field not in readable]
        return ReauthorizedConditions(runnable=runnable, disabled=disabled)

    def _filterable_columns(self, object_type: str, visible_type_def: dict) -> set:
        columns = set()
        if visible_type_def["id_field"] is not None:
            columns.add(visible_type_def["id_field"])
        for field_name, field_info in visible_type_def["fields"].items():
            if is_searchable_field(field_info):
                columns.add(field_name)
        return columns

    def search_object(self, user_record: UserRecord, object_type: str,
                       conditions: "list[FieldFilter] | None" = None,
                       visible_schema: dict | None = None,
                      context: RequestContext | None = None) -> list:
        """IDs the caller may see, matching every condition.

        TAKES CONDITIONS, not a {field: value} dict. The dict could
        express only equality -- one value per field -- so selecting
        two values on a chart had no representation at all, and
        validate_filter() could never reject anything because every
        condition was built here and correct by construction.

        Field names are checked against the caller's OWN visible
        schema, so a field they cannot read is indistinguishable from
        one that does not exist. That check needs a caller, which is
        why it lives here and not in the vocabulary.
        """
        conditions = conditions or []
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
        for condition in conditions:
            if condition.field not in valid_columns:
                # Generic, no field list -- revealing "valid: [...]"
                # here would hand back exactly the schema visible_schema()
                # just deliberately hid.
                raise ValueError("Invalid search criteria")
            # Now reachable, and able to REJECT: the operator comes
            # from the caller rather than being constructed here.
            validate_filter(condition, self._declared_type(object_type, condition.field))

        adapter, resolved_type_config = self._resolve_shared_storage(
            object_type, [condition.field for condition in conditions]
        )

        # Translates each criteria KEY (a field name) to its real SQL
        # column name -- see get_column_for_field()'s own docstring for
        # why the id_field needs its own handling (it isn't a regular
        # entry in type_schema["fields"] at all).
        # Field names become column names; operator and value survive.
        translated = [
            FieldFilter(
                field=get_column_for_field(resolved_type_config, condition.field),
                operator=condition.operator,
                value=condition.value,
            )
            for condition in conditions
        ]
        candidate_ids = self._find_ids_with_fallback(
            adapter, object_type, translated, resolved_type_config
        )
        candidate_ids = self._reconcile_search_with_pending_writes(
            object_type, conditions, candidate_ids, adapter, resolved_type_config
        )
        action = f"read:{object_type}"
        candidate_ids = self._without_deleted(object_type, candidate_ids)

        # Resolves every candidate's security value in bulk before the
        # per-object checks below. check_access() itself is unchanged --
        # same call, same order, same audit logging -- it just finds
        # the values already cached instead of reading one at a time.
        self._prefetch_security_values(object_type, candidate_ids)

        return [
            candidate_id for candidate_id in candidate_ids
            if check_access(self, user_record, self.roles, object_type, candidate_id, action, context)
        ]

    def free_text_searchable_fields(self, user_record: UserRecord, object_type: str,
                                     visible_schema: dict | None = None) -> list[str]:
        # PUBLIC (unlike _filterable_columns() above) -- api/routes.py's
        # own free-text search endpoint needs this SAME list to know
        # which fields to show as each result's own summary row,
        # matching exactly what search_object_free_text() itself
        # actually searched, not a second, independently-guessed set
        # that could silently drift out of sync with it (the same
        # single-source-of-truth discipline is_searchable_field() was
        # already built to enforce elsewhere in this file).
        #
        # Narrower than _filterable_columns() above, deliberately: free-
        # text CONTAINS search only makes sense over plain "data"
        # fields, not the id_field or a forward-link field (both real,
        # useful EXACT-match filter keys for search_object(), but
        # substring-searching a raw id/foreign-key value isn't what a
        # human typing a few characters of a name or email is after).
        # Also excludes any field backed by a non-primary storage (MDO)
        # -- see search_object_free_text()'s own docstring for why.
        visible = visible_schema if visible_schema is not None else self.visible_schema(user_record)
        visible_type_def = visible.get(object_type)
        if visible_type_def is None:
            return []
        return [
            field_name for field_name, field_info in visible_type_def["fields"].items()
            if field_info["type"] == "data" and get_field_storage_name(field_info) is None
        ]

    def search_object_free_text(self, user_record: UserRecord, object_type: str, query_text: str,
                                 visible_schema: dict | None = None,
                                 conditions: list | None = None,
                                context: RequestContext | None = None) -> list:
        """Free-text search, optionally narrowed by structured filters.

        TWO CONTEXTS, COMBINED, which is how every search engine that
        does both handles it: the text query decides what MATCHES, the
        conditions decide what is ELIGIBLE, and a result must satisfy
        both. Elasticsearch calls these query context and filter
        context and ANDs them in one bool; this is the same shape with
        one text clause.

        That split is why the filter vocabulary stays AND-only. Free
        text already ORs across every searchable column -- inside
        find_ids_matching_text, where it belongs -- so the OR a user
        needs exists without the vocabulary having to grow one. A
        `should` clause in the filter language would have been a much
        larger change for the same result.

        It is what makes charts and a table describe ONE object set:
        the table's text query and a chart click both narrow the same
        thing, rather than being two queries nobody can combine.
        """
        # The human-facing, browse/search counterpart to search_object()
        # above -- a forgiving, CONTAINS match across every visible,
        # plain-data, primary-storage field at once, not an exact match
        # against one named field. Built for a real end user typing a
        # few characters of a name or email into a search box, not for
        # the model's own precise, single-field search_object() steps
        # (which stay completely unchanged by this addition -- see
        # this method's own AI-notes for the fuller reasoning on why
        # this is a new, separate method rather than a mode flag on the
        # existing one).
        #
        # An empty/blank query_text returns EVERY visible object of
        # this type -- the natural "browse, nothing typed yet" default
        # for a UI landing on this type, not an empty result.
        #
        # DELIBERATE V1 SCOPE BOUNDARIES, both worth stating explicitly:
        # - MDO-backed fields (additional_storage) are excluded from the
        #   search entirely, matching this project's own existing,
        #   already-justified "one storage per search" boundary for
        #   search_object() itself (see _resolve_shared_storage()'s own
        #   docstring) -- not a new gap, the same one, applied here too.
        # - Does NOT reconcile against write_log.py's own pending writes
        #   the way search_object() does via _reconcile_search_with_
        #   pending_writes() -- that mechanism is built around exact-
        #   match criteria (field: value pairs) and doesn't generalize
        #   cleanly to a substring match against a possibly-pending
        #   value. An object mid-update could therefore, briefly, be
        #   missing from (or wrongly present in) a free-text search for
        #   its own in-flight change -- the same class of torn-state
        #   window search_object() itself used to have before that
        #   mechanism existed. Acceptable for a first, foundational
        #   version of a browse/search UI (the window is normally
        #   brief, and this is a discovery aid, not a correctness-
        #   sensitive read) -- not acceptable to leave forever
        #   undocumented, which is why it's spelled out here.
        visible = visible_schema if visible_schema is not None else self.visible_schema(user_record)
        visible_type_def = visible.get(object_type)
        if visible_type_def is None:
            if object_type not in self.schema:
                self.audit_log.log_unknown_reference(user_record.user_id, object_type)
            else:
                self.audit_log.log_access(user_record.user_id, object_type, None, f"read:{object_type}",
                                           mac_allowed=None, rbac_allowed=False)
            return []

        searchable_fields = self.free_text_searchable_fields(user_record, object_type, visible)
        if not searchable_fields:
            return []

        adapter, resolved_type_config = self._resolve_shared_storage(object_type, searchable_fields)
        columns = [get_column_for_field(resolved_type_config, field_name) for field_name in searchable_fields]

        if query_text.strip():
            candidate_ids = adapter.find_ids_matching_text(object_type, columns, query_text, resolved_type_config)
            if conditions:
                # Filter context: intersect, rather than re-running the
                # text search with conditions folded in. The adapter's
                # text search takes columns and a string, and widening
                # its contract to also take conditions would give two
                # ways to express the same filter.
                eligible = set(
                    self._find_ids_with_fallback(
                        adapter, object_type,
                        self._translate_conditions(
                            object_type, conditions, resolved_type_config, visible_type_def
                        ),
                        resolved_type_config,
                    )
                )
                candidate_ids = [oid for oid in candidate_ids if oid in eligible]
        else:
            # No text: the conditions ARE the query.
            candidate_ids = self._find_ids_with_fallback(
                adapter, object_type,
                self._translate_conditions(
                    object_type, conditions or [], resolved_type_config, visible_type_def
                ),
                resolved_type_config,
            )

        action = f"read:{object_type}"
        candidate_ids = self._without_deleted(object_type, candidate_ids)
        # Same bulk pre-resolution as search_object() above.
        self._prefetch_security_values(object_type, candidate_ids)
        return [
            candidate_id for candidate_id in candidate_ids
            if check_access(self, user_record, self.roles, object_type, candidate_id, action, context)
        ]

    def _declared_type(self, object_type: str, field_name: str) -> str | None:
        """A field's declared data_type, or None when it declares none.

        None means "no expectation to violate" -- declaring a type is
        how an author opts into operator checking, the same bargain the
        mutation-value check makes.
        """
        fields = (self.schema.get(object_type) or {}).get("fields") or {}
        return (fields.get(field_name) or {}).get("data_type")

    def _translate_conditions(self, object_type: str, conditions: list,
                               resolved_type_config: dict, visible_type_def: dict) -> list:
        """Field names to column names, validated on the way.

        Shared by search_object() and search_object_free_text() so
        there is one definition of "may this caller filter on this
        field", not two that could drift.
        """
        translated = []
        valid_columns = self._filterable_columns(object_type, visible_type_def)
        for condition in conditions:
            if condition.field not in valid_columns:
                # Same message whether the field is UNREADABLE or
                # absent -- uniform denial, exactly as search_object()
                # does it.
                raise ValueError("Invalid search criteria")
            validate_filter(condition, self._declared_type(object_type, condition.field))
            translated.append(
                FieldFilter(
                    field=get_column_for_field(resolved_type_config, condition.field),
                    operator=condition.operator,
                    value=condition.value,
                )
            )
        return translated

    def _find_ids_with_fallback(self, adapter, object_type: str, conditions: list,
                                 resolved_type_config: dict) -> list:
        """Pushes what the storage declared it can express; applies the
        rest here.

        THE MEDIATOR SPLITS, using `pushable_operators` the adapter
        declared, rather than asking and retrying on refusal. An
        earlier version had adapters raise UnsupportedFilter and this
        retry with NOTHING pushed, which made one unsupported operator
        cost the whole query: a `contains` alongside three ranges
        scanned everything, measured at 40x the pushed-down time for
        the same answer.

        Partial pushdown was rejected then because an adapter reporting
        which conditions it took could disagree with what it did, and
        that disagreement returns wrong rows silently. Declaring up
        front removes the report and with it the mismatch -- only the
        mediator decides, and it asks for nothing else.

        This is the SQL/Python alignment rule's own exception, and it
        is now as narrow as it can be: exactly the operators a storage
        cannot express come back here, and nothing else.
        """
        pushable: frozenset[str] = getattr(adapter, "pushable_operators", frozenset())
        pushed = [c for c in conditions if c.operator in pushable]
        remaining = [c for c in conditions if c.operator not in pushable]

        candidate_ids = adapter.find_ids(object_type, pushed, resolved_type_config)
        if not remaining:
            return candidate_ids
        return self._apply_conditions_in_python(
            adapter, candidate_ids, remaining, resolved_type_config
        )

    def _apply_conditions_in_python(self, adapter, candidate_ids: list,
                                     conditions: list, resolved_type_config: dict) -> list:
        """Evaluates conditions a storage could not express.

        Reads only the columns the remaining conditions name, for only
        the ids the pushed-down half returned -- so the cost is
        proportional to what the engine could NOT narrow, not to the
        table.
        """
        if not conditions or not candidate_ids:
            return candidate_ids
        id_column = resolved_type_config["storage"]["id_column"]
        columns = sorted({condition.field for condition in conditions})
        rows = adapter.read_fields_for_ids(
            resolved_type_config["storage"]["table"], id_column,
            candidate_ids, columns, resolved_type_config,
        )
        return [
            row[id_column] for row in rows
            if all(row_matches(row, condition) for condition in conditions)
        ]

    def _reconcile_search_with_pending_writes(self, object_type: str, conditions: list, candidate_ids: list,
                                               adapter: ExternalReadAdapter, resolved_type_config: dict) -> list:
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
            # Only the FIELD NAMES matter here -- whether a pending
            # write touched anything the search filtered on. The
            # operator and value are irrelevant to that question, which
            # is why this survived the change from a dict unchanged
            # apart from how the names are read out.
            if entry["object_type"] == object_type
            and set(entry["changes"]) & {condition.field for condition in conditions}
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
                    object_type, object_id, condition.field, adapter,
                    resolved_type_config,
                ) is not None
                and row_matches(
                    {condition.field: self._read_field_with_log_check(
                        object_type, object_id, condition.field, adapter,
                        resolved_type_config,
                    )},
                    condition,
                )
                for condition in conditions
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

    def search_around(self, user_record: UserRecord, object_type: str, conditions: list,
                       link_field: str,
                      context: RequestContext | None = None) -> list:
        """Follows a link from every object matching criteria, returning
        the ids on the far side that the caller can also see.

        Foundry's own Search Around: "takes an incoming object set and
        runs a secondary filter on another object set based on a
        certain property of the incoming set." Asking "every
        transaction belonging to a us-west customer" is one call here
        rather than one per customer.

        MAC IS APPLIED ON BOTH SIDES, and that is the point. The source
        set comes from search_object(), so a caller only traverses from
        objects they can see; the resulting target ids are then
        authorized individually, so following a link can never reveal
        an object the caller could not have read directly. Skipping
        either check would turn a link into a way around the security
        boundary.

        Returns a deduplicated list -- two source objects legitimately
        linking to the same target should yield it once.
        """
        source_ids = self.search_object(user_record, object_type, conditions)
        if not source_ids:
            return []

        visible_type_def = self.visible_schema(user_record).get(object_type)
        field_info = (visible_type_def or {}).get("fields", {}).get(link_field)
        if field_info is None or not is_link_field(field_info):
            # Same uniform-denial shape as every other read: a caller
            # learns nothing about whether the field exists, is a link,
            # or is merely ungranted.
            return []

        target_type = get_link_target(field_info)
        raw_field_info = self.schema[object_type]["fields"][link_field]
        if "via_table" not in raw_field_info:
            # A FORWARD link -- the id lives on the source object
            # itself, so there is nothing to traverse in batch; reading
            # the field per source is already the whole operation.
            targets = []
            for source_id in source_ids:
                value = self.get_field(user_record, object_type, source_id, link_field)
                if value is None:
                    continue
                targets.extend(value if isinstance(value, list) else [value])
        else:
            target_adapter = self._adapter_for(target_type)
            target_id_column = self.schema[target_type]["storage"]["id_column"]
            grouped = target_adapter.resolve_reverse_links_batch(
                source_ids, raw_field_info, target_id_column
            )
            targets = [
                target_id for target_ids in grouped.values() for target_id in target_ids
            ]

        action = f"read:{target_type}"
        # Targets are a DIFFERENT object type from the sources, so this
        # prefetch is for the target type -- the source side was already
        # resolved by the search_object() call at the top of this method.
        self._prefetch_security_values(target_type, list(targets))
        seen = set()
        allowed = []
        for target_id in targets:
            if target_id in seen:
                continue
            seen.add(target_id)
            if check_access(self, user_record, self.roles, target_type, target_id, action, context):
                allowed.append(target_id)
        return allowed

    def edit_history(self, user_record: UserRecord, object_type: str, object_id: Any,
                      limit: int | None = None, offset: int = 0,
                     context: RequestContext | None = None) -> tuple[list[dict], int]:
        """Every applied write to one object, newest first, if the
        caller may read that object.

        Foundry's own rule, quoted because it settles the security
        question cleanly: "Users who have access to the current state
        of an object (object with the same primary key) can access the
        entire history of the object." So authorization is the SAME
        check as reading the object itself -- no separate grant, and no
        way to learn about an object's past that you could not learn
        about its present.

        A caller who cannot read the object gets an empty list, not an
        error: the same uniform denial every other read path uses, so
        the response never distinguishes "no history" from "not
        allowed" from "no such object".

        CHANGED FIELDS ARE FILTERED per-field, not just per-object. A
        caller granted read:Customer but not read:Customer.email must
        not learn that the email changed, or to what, by reading
        history -- that would be a genuine way around field-level RBAC.
        An entry whose changes are entirely ungranted still appears,
        with empty changes, because the FACT that someone edited this
        object at a given time is exactly what an audit trail is for.
        """
        if self.write_log is None:
            return [], 0
        if not check_access(self, user_record, self.roles, object_type, object_id,
                            f"read:{object_type}", context):
            return [], 0

        readable = {
            field_name
            for field_name in (self.schema.get(object_type) or {}).get("fields", {})
            if authorize(user_record, self.roles, f"read:{object_type}.{field_name}")
        }
        # Returns (page, total) together so the MAC check above happens
        # ONCE. A separate count method would have to repeat it, and a
        # count that forgot would leak how much history exists for an
        # object the caller cannot read.
        entries = [
            {**entry, "changes": {k: v for k, v in entry["changes"].items() if k in readable}}
            for entry in self.write_log.edit_history(object_type, object_id, limit, offset)
        ]
        return entries, self.write_log.edit_history_count(object_type, object_id)

    def count_objects(self, user_record: UserRecord, object_type: str, conditions: list) -> int:
        """How many objects of this type the CALLER can see, matching
        criteria.

        The count is of objects this specific user is authorized to
        read, never the raw row count -- two users running the same
        count legitimately get different answers, and a count that
        ignored MAC would leak the existence of rows outside the
        caller's boundary.

        Deliberately built on search_object() rather than a SQL
        COUNT(*): the criteria filter is pushed to the engine there,
        but MAC is applied per object in Python afterwards (following
        security.via_field chains that can cross silos), so a
        engine-side COUNT would count rows the caller cannot see. That
        is the same constraint Foundry's own Object Set Service works
        under, and the reason it is a service rather than exposed SQL.
        """
        return len(self.search_object(user_record, object_type, conditions))

    def aggregate_by_field(self, user_record: UserRecord, object_type: str, conditions: list,
                            group_by: str | None, aggregate: str, field_name: str | None = None) -> dict:
        """Aggregates a field over the objects the caller can see.

        `aggregate` is one of count/sum/avg/min/max -- the same set
        Foundry's own aggregate API exposes. `field_name` is required
        for every aggregate except count, which needs no field.
        `group_by` of None aggregates the whole matching set into a
        single result under the key None.

        Returns {group_value: metric}. Null group values are EXCLUDED,
        matching Foundry's documented behaviour: "null properties are
        never included in groupBy or aggregation computations."

        Reads in BULK. The naive version -- get_object() per matching
        id -- cost 16,045 SQL queries to aggregate 2,004 objects,
        measured directly. Authorization is still resolved per object,
        because it must be, but the DATA is read once.
        """
        if aggregate not in _AGGREGATES:
            raise ValueError(f"Unknown aggregate {aggregate!r} -- expected one of {sorted(_AGGREGATES)}")
        if aggregate != "count" and field_name is None:
            raise ValueError(f"aggregate {aggregate!r} requires a field_name")

        visible_ids = set(self.search_object(user_record, object_type, conditions))
        if not visible_ids:
            return {}

        wanted = [name for name in (group_by, field_name) if name is not None]
        if not wanted:
            # count over the whole set, with no grouping and no field:
            # the answer is the size of the authorized set itself, and
            # there is genuinely nothing to read. Without this, the
            # bulk read is asked for zero columns, returns nothing, and
            # the count comes back empty -- a real bug caught by
            # testing the no-field count path.
            return {None: len(visible_ids)}

        rows = self._read_fields_for_ids(user_record, object_type, visible_ids, wanted)

        grouped: dict[Any, list] = {}
        for object_id, row in rows.items():
            group_value = row.get(group_by) if group_by is not None else None
            if group_by is not None and group_value is None:
                # Excluded, per Foundry's own documented rule.
                continue
            value = row.get(field_name) if field_name is not None else object_id
            if field_name is not None and value is None:
                continue
            grouped.setdefault(group_value, []).append(value)

        return {group: _AGGREGATES[aggregate](values) for group, values in grouped.items()}

    def _read_fields_for_ids(self, user_record: UserRecord, object_type: str,
                              object_ids: set, field_names: list[str]) -> dict:
        """Reads several fields for many ALREADY-AUTHORIZED objects in
        one adapter call per storage, rather than one per field per
        object.

        object_ids must already have passed check_access() -- this
        method performs no authorization of its own, which is why it is
        private and why every caller resolves visibility first. Field
        names are still RBAC-checked individually, since a caller
        authorized to read an object is not thereby authorized to read
        every field of it.
        """
        readable = [
            name for name in field_names
            if authorize(user_record, self.roles, f"read:{object_type}.{name}")
        ]
        if not readable:
            return {}

        adapter, resolved_type_config = self._resolve_shared_storage(object_type, readable)
        id_column = resolved_type_config["storage"]["id_column"]
        columns = [get_column_for_field(resolved_type_config, name) for name in readable]

        # Filtered IN THE ENGINE -- see read_fields_for_ids(). Set
        # membership is exactly the work a database is for, and doing
        # it in Python meant reading a whole table to return a page.
        raw = adapter.read_fields_for_ids(
            resolved_type_config["storage"]["table"], id_column,
            list(object_ids), columns, resolved_type_config,
        )

        by_id = {}
        for row in raw:
            object_id = row[id_column]
            by_id[object_id] = {
                name: self._read_field_with_log_check(
                    object_type, object_id, name, adapter, resolved_type_config
                )
                if self.write_log is not None
                else row[column]
                for name, column in zip(readable, columns, strict=True)
            }
        return by_id

    def get_field(self, user_record: UserRecord, object_type: str, object_id: Any, field_name: str,
                   context: RequestContext | None = None):
        # NEVER raises for "field/type doesn't exist" or "not authorized"
        # -- both return None.
        if object_type not in self.schema:
            # Distinguishes, for auditing, a genuinely unknown
            # object_type from an ordinary RBAC/MAC denial -- see
            # log_unknown_reference()'s own docstring.
            self.audit_log.log_unknown_reference(user_record.user_id, object_type)
            return None

        action = f"read:{object_type}.{field_name}"
        access_allowed = check_access(self, user_record, self.roles, object_type, object_id, action, context)

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

    def get_object(self, user_record: UserRecord, object_type: str, object_id: Any, field_names: list[str]) -> dict:
        # A thin, per-field loop around get_field() above -- reuses its
        # ENTIRE RBAC/MAC/audit/MDO-storage-resolution/write-log-
        # reconciliation logic exactly, unchanged, once per field. This
        # exists ONLY to save the MODEL real hops (one request instead
        # of N separate get_field calls against max_hops), not to
        # reduce the number of underlying storage reads or introduce
        # any new authorization/data logic of its own -- see this
        # method's own AI-notes for why batching the UNDERLYING
        # storage queries (e.g. resolving shared storage once for
        # every field that happens to share one) was considered and
        # deliberately deferred, not attempted here.
        #
        # Same "never raises" contract as get_field() -- an unknown
        # field, an unknown object_type, or a genuine RBAC/MAC denial
        # all resolve to that field's own entry being None, exactly as
        # a caller would see calling get_field() for it directly; a
        # partially-authorized request (some fields granted, some not)
        # returns a dict mixing real values and Nones, never raises or
        # silently drops the denied ones.
        # Resolves this object's security value ONCE before the loop.
        #
        # get_field() calls check_access() per field, and each call
        # resolves MAC independently -- so reading four fields of one
        # object cost eight queries, two per field, for data living in
        # a single row. Warming the cache first makes every check after
        # the first a dictionary lookup: 2N becomes N+1.
        #
        # Deliberately warms rather than restructuring the loop into a
        # bulk read. get_field() also applies per-field RBAC, logs
        # unknown fields, follows reverse links to a different adapter
        # entirely, and masks values against pending writes. Replacing
        # it would mean reimplementing all of that; this changes only
        # what the existing path costs.
        #
        # ONLY IF NOT ALREADY CACHED, which matters more than it looks.
        # _prefetch_security_values() CLEARS the cache before filling
        # it, so warming unconditionally here would make a caller
        # reading a page of results defeat itself: search_object()
        # resolves security for all fifty rows, then the first
        # get_object() throws that away and the remaining forty-nine
        # each re-resolve their own. The unconditional version was
        # committed and measured at exactly 4 queries per row, with no
        # sharing across the page at all.
        if (object_type, str(object_id)) not in self._security_value_cache and (
            object_type, str(object_id)
        ) not in self._security_link_cache:
            self._prefetch_security_values(object_type, [object_id])

        return {
            field_name: self.get_field(user_record, object_type, object_id, field_name)
            for field_name in field_names
        }
