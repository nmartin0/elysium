"""
write_mediator.py  (the write path -- generic, org-agnostic)

Takes a pre-resolved UserRecord, not a raw user_id -- same reduction as
DataMediator: WriteMediator no longer holds users/security_attribute at
all, only roles (still shared, static config, unaffected by this
change).

Two stages: propose_action() checks RBAC+MAC, validates parameters,
evaluates submission criteria, and resolves the action's own declared
mutations into a snapshot of the fields about to change;
confirm_and_execute() re-verifies that snapshot ATOMICALLY at write
time (per-object lock + adapter.write_fields()'s conditional SQL),
preventing lost updates. PendingWrite is frozen -- nothing about a
proposed write can change between human approval and execution.

NAMED ACTIONS -- matches Palantir Foundry's own action-type model
directly (verified against their docs, not assumed): a proposal names
a NAMED, independently-governed operation (execute:{action_name}, one
grant per action), not a generic CRUD verb with free-form field input.
See propose_action()'s own docstring for the full mechanism.

This file used to hold a SECOND, parallel proposal path (propose_write()
-- free-form write:{type}.{field}/create:{type} grants, the ORIGINAL
model before named actions existed) during this project's own
build-and-prove-in-isolation migration phase. That path has since been
fully migrated and removed -- see git history on the
action-types-redesign branch for the migration pass itself. Every real
schema now declares action_types; there is no remaining fallback.

Used by: core/agent/agentic_loop.py's AgentLoop (write_mediator +
         confirm_write callback, both None if writes are disabled)
"""

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import UserRecord, authorize
from core.ontology.interface import ExternalReadAdapter, ExternalWriteAdapter
from core.ontology.mediator import DataMediator
from core.ontology.schema import get_column_for_field
from core.ontology.submission_criteria import evaluate_submission_criteria
from core.ontology.write_log import WriteLogWriter

if TYPE_CHECKING:
    # A real, TYPE_CHECKING-only intersection type -- never a runtime
    # class, never instantiated -- for the one, real, recurring need in
    # this file: several private helpers below (_read_group_fields,
    # _write_fields_with_limiter, _create_object_with_limiter) are only
    # ever called with an adapter obtained via self._adapter_mediator
    # (this class's own internal, write-capable DataMediator -- see
    # this class's own __init__ docstring), which in real, concrete
    # practice always holds an adapter that is BOTH read- and write-
    # capable (adapters/sqlite_adapter.py's own SQLiteWriteAdapter
    # genuinely extends both ExternalReadAdapter and
    # ExternalWriteAdapter). Neither ExternalReadAdapter nor
    # ExternalWriteAdapter alone has both method sets; this says so
    # explicitly, at the one real place it's needed, rather than
    # scattering an unexplained cast() at every individual call site.
    class _ReadWriteAdapter(ExternalReadAdapter, ExternalWriteAdapter):
        pass


def _fields_to_columns(resolved_type_config: dict, values_by_field: dict) -> dict:
    # Standalone, not a method -- needs no WriteMediator state, and is
    # called once per storage GROUP (see _group_changes_by_storage()),
    # each with its own resolved_type_config.
    return {
        get_column_for_field(resolved_type_config, field_name): value
        for field_name, value in values_by_field.items()
    }


@dataclass(frozen=True)
class SubWrite:
    # One object's own share of a (possibly multi-object) proposed
    # write -- see PendingWrite's own docstring immediately below for
    # why this is a separate dataclass, nested inside a tuple, rather
    # than PendingWrite itself still holding one flat object_type/
    # object_id/changes triple directly the way it used to.
    #
    # object_id is ALWAYS the real, concrete id here, for BOTH "update"
    # and "create" -- unlike this dataclass's own predecessor
    # (PendingWrite.object_id), which used to stay None for "create"
    # specifically, forcing every consumer (see the old
    # _apply_create_via_log()) to separately re-derive the real id from
    # changes[id_field] each time it was needed. propose_action()
    # already knows the real id at construction time either way (the
    # object_id it was called with for "update"; changes[id_field],
    # already validated present, for "create") -- resolving it once,
    # here, removes that whole re-derivation dance, and gives every
    # future consumer (locking, duplicate-object validation, the
    # write_log_batches JSON) a real id to work with directly, with no
    # special-casing by operation kind.
    object_type: str
    object_id: Any
    operation: Literal["update", "create", "delete"]
    changes: dict
    expected_current_values: dict = field(default_factory=dict)  # for update lost-update checks


@dataclass(frozen=True)
class PendingWrite:
    # sub_writes is ALWAYS at least one entry, even for what looks like
    # an ordinary single-object action -- there is deliberately no
    # separate "single-object" representation living alongside a
    # "multi-object" one. propose_action(), core/ontology/
    # action_types.py's own schema-load validation, AND confirm_and_
    # execute()'s own apply logic all fully support more than one:
    # every write goes through _apply_batch(), one sub_write or many,
    # with no special case for either. (This comment used to say the
    # apply side "still only ever applies sub_writes[0]" -- true when
    # written, stale since the batch work landed. See this file's own
    # AI-notes and write_log.py's MULTI-OBJECT BATCHES section.)
    #
    # action_type_name is the action's own real, raw name (e.g.
    # "TransferFunds") -- distinct from description, which is a
    # human-formatted string that HAPPENS to embed this name but isn't
    # meant to be parsed back apart by anything. Added specifically so
    # confirm_and_execute()'s own audit logging (log_pre()'s action_id)
    # has a real identifier for the ACTION itself to use, the same way
    # propose_action()'s own earliest RBAC-denial log_access() call
    # already does -- neither needs, or should ever need, to fall back
    # to guessing at a single object_type the way the pre-sub_writes
    # design used to.
    sub_writes: tuple[SubWrite, ...]
    user_id: str
    description: str
    action_type_name: str


class WriteMediator:
    def __init__(
        self, mediator: DataMediator, write_adapters: dict[str, ExternalWriteAdapter], roles: dict, action_types: dict
    ):
        # action_types is required, not optional -- a WriteMediator's
        # only real capability is propose_action(), which is useless
        # without declared actions. Verified directly: EVERY real
        # construction site already passes it explicitly; nothing
        # depends on a None-shaped default. Keeping optionality alive
        # after migration is actually complete is compat cruft, not a
        # real capability -- removed rather than left as unused,
        # confusing dead weight.
        self.mediator = mediator
        self.roles = roles
        self.action_types = action_types
        # write_adapters -- a real, SEPARATE, independent set of
        # adapters, never mediator's own (see this class's own
        # AI-notes for the full story: Phase 0 of the read-only mirror
        # initiative, a real, found prerequisite -- WriteMediator used
        # to borrow SIX of DataMediator's own private methods
        # (_resolve_shared_storage, _write_limiter_for_silo,
        # _locks_for_objects, _type_schema, _read_field_with_log_check,
        # _security_allowed) by reaching directly into
        # self.mediator, meaning this class had no adapter
        # identity of its own at all. Once DataMediator's own adapters
        # move to a genuinely read-only credential, that borrowing
        # would have silently broken every real write in the system.
        #
        # A real, SEPARATE, internal DataMediator instance is built
        # here specifically to REUSE those six methods' own, already-
        # correct, already-tested implementations -- not a second,
        # parallel reimplementation of the same logic, matching this
        # project's own DRY discipline. schema/silo_for_type/roles are
        # read-only, ontology-describing dicts, not live connections --
        # confirmed directly safe to keep sharing from `mediator`
        # itself, unlike the adapters themselves. write_log/audit_log
        # ALSO stay the SAME, shared instances mediator itself holds
        # -- deliberately, confirmed directly as still correct to
        # share (both are genuinely cross-cutting infrastructure, not
        # a silo-specific connection/adapter at all; see this class's
        # own write_log/audit_log properties immediately below, which
        # keep reading from `mediator` directly, unchanged).
        # cast(): write_adapters is dict[str, ExternalWriteAdapter] --
        # DataMediator's own __init__ statically expects dict[str,
        # ExternalReadAdapter], since that's genuinely all a normal,
        # real, read-only DataMediator ever needs. This specific
        # DataMediator instance is never that normal case, though --
        # it is WriteMediator's own internal, private helper (never
        # returned, never handed to any other caller), built
        # specifically to reuse DataMediator's own six already-
        # correct methods against write_adapters instead of
        # duplicating them -- so the real, concrete adapters it holds
        # genuinely are ExternalWriteAdapter instances throughout (in
        # practice, adapters/sqlite_adapter.py's own SQLiteWriteAdapter,
        # which -- see that class's own docstring -- also genuinely
        # implements ExternalReadAdapter's own contract too, via real
        # inheritance from SQLiteReadAdapter). The cast is safe
        # specifically because this instance's own adapters are never
        # read through this constructor's own, narrower, static type.
        self._adapter_mediator = DataMediator(
            mediator.schema, cast("dict[str, ExternalReadAdapter]", write_adapters), mediator.silo_for_type, roles,
            write_log=mediator.write_log, audit_log=mediator.audit_log,
        )
        # write_log is NOT taken as a separate parameter and stored
        # independently -- see this class's own write_log property.
        # WriteMediator has no legitimate reason to use a DIFFERENT
        # write_log than the DataMediator it wraps reads from; reading
        # the SAME shared instance from mediator makes that
        # structurally true rather than something enforced by a
        # runtime "do these two values match" check (which used to
        # exist here, and no longer needs to -- there's only ever one
        # value to begin with now).
        if mediator.write_log is None:
            raise ValueError(
                "WriteMediator requires its DataMediator to be constructed with a "
                "write_log -- confirm_and_execute() depends on it entirely for both "
                "'update' and 'create'."
            )
        # A real, SEPARATE, write-capable WriteLogWriter, derived from
        # the reader's OWN db_path -- deliberately not taken as its own
        # constructor parameter. Deriving it this way makes it
        # structurally impossible for the two to point at different
        # physical databases (the exact "two values that could
        # accidentally drift apart" problem this class's own write_log
        # property was originally written to avoid), while still giving
        # this class the genuinely write-capable instance it needs --
        # see that property's own docstring.
        self._write_log_writer = WriteLogWriter(mediator.write_log.db_path)

    @property
    def write_log(self) -> WriteLogWriter:
        # A real, SEPARATE WriteLogWriter -- no longer the same
        # instance self.mediator holds. A necessary change, matching
        # the same real precedent write_adapters already set in this
        # same class: DataMediator's own write_log is now a genuinely
        # read-only WriteLogReader (structurally incapable of the
        # log_pending_*/mark_* writes every method below depends on),
        # so borrowing it would break every real write. Both still
        # point at the SAME physical database file, so there is still
        # exactly one real write log per deployment -- only the
        # capability differs, which is the entire point of the split.
        return self._write_log_writer

    @property
    def audit_log(self) -> AuditLog:
        # Always the SAME instance self.mediator itself holds -- never
        # a separately-stored copy, matching this class's own
        # write_log property immediately above, for the identical
        # reason. No type-narrowing assert needed here, unlike that
        # one -- mediator.audit_log is never Optional in the first
        # place (see DataMediator's own docstring on why).
        return self.mediator.audit_log

    def _group_changes_by_storage(self, object_type: str, changes: dict) -> list[tuple]:
        # Resolves EACH field individually (a list of exactly one field
        # name each), reusing DataMediator._resolve_shared_storage()
        # directly rather than duplicating its own internal per-field
        # storage-resolution logic -- then groups fields that resolved
        # to the SAME storage back together, so fields sharing one
        # storage still go through ONE write_fields() call (real
        # SQL-level atomicity + efficiency for the common, single-
        # storage case), while fields on DIFFERENT storages become
        # separate groups instead of the outright rejection a single,
        # whole-dict _resolve_shared_storage() call would otherwise
        # raise for spanning more than one storage.
        #
        # Grouped by id(resolved_type_config["storage"]) -- that dict
        # is the SAME object instance every time for the same storage
        # name (type_schema, and therefore its "storage"/
        # "additional_storage" entries, is loaded once and never
        # rebuilt -- see DataMediator._resolve_shared_storage()), so
        # comparing by identity is exact. Deliberately NOT id(adapter)
        # alone -- two different storage names could theoretically
        # share the same underlying silo/adapter while still needing
        # different resolved_type_config (a different table), which
        # grouping by adapter identity alone would incorrectly merge.
        groups: dict[int, tuple] = {}
        for field_name in changes:
            # cast(): this method's own adapter always genuinely comes
            # from self._adapter_mediator, this class's own internal,
            # write-capable helper -- see this class's own __init__
            # docstring, and the module-level _ReadWriteAdapter type's
            # own comment, for why the real, concrete object here is
            # always both read- and write-capable even though
            # _resolve_shared_storage()'s own STATIC return type
            # (inherited, unchanged, from DataMediator) only ever
            # promises ExternalReadAdapter.
            adapter, resolved_type_config = self._adapter_mediator._resolve_shared_storage(object_type, [field_name])
            adapter = cast("_ReadWriteAdapter", adapter)
            key = id(resolved_type_config["storage"])
            if key not in groups:
                groups[key] = (adapter, resolved_type_config, {})
            groups[key][2][field_name] = changes[field_name]
        return list(groups.values())

    def _read_group_fields(self, object_type: str, object_id: Any, adapter: "_ReadWriteAdapter",
                            resolved_type_config: dict, field_names) -> dict:
        # THE single home for "read the current, live value of each
        # field in one already-resolved storage group, straight from
        # the adapter" -- was duplicated three times before this
        # refactor (propose_action()'s own pre-write snapshot,
        # _resume_one_update_entry()'s initial read, and that SAME
        # method's own post-race re-read), identical logic every time.
        # Direct adapter reads, not DataMediator._read_field_with_log_check()
        # -- every caller here is deliberately reading the REAL,
        # physical backend state to compare against, not the log's own
        # masked value; using the log-aware read would be self-
        # defeating for exactly what these callers need to know.
        return {
            field_name: adapter.get_raw_field(
                object_type, object_id, get_column_for_field(resolved_type_config, field_name), resolved_type_config,
            )
            for field_name in field_names
        }

    def _write_fields_with_limiter(self, object_type: str, object_id: Any, adapter: "_ReadWriteAdapter",
                                    resolved_type_config: dict, new_values: dict, expected_values: dict) -> bool:
        # THE single home for "resolve THIS group's own silo's
        # concurrency limiter, then call write_fields() under it" --
        # was duplicated at both places an update group's write is
        # actually attempted (the fresh-apply path in
        # _apply_one_update(), and the resume path in
        # _resume_one_update_entry()), identical shape at each.
        #
        # Resolving per-GROUP's own silo here, not once per pending
        # write from object_type alone, closed a real bug caught by
        # directly tracing this exact call chain, not just reasoned
        # about: object_type alone ALWAYS resolves to the PRIMARY
        # silo's limiter (that lookup no longer exists at all --
        # removed once this fix left it with zero remaining callers).
        # A group writing to a DIFFERENT storage (any MDO
        # additional_storage) would silently borrow the PRIMARY silo's
        # concurrency limiter instead of its own -- wrong capacity
        # accounting in both directions: under-protecting the real
        # target silo if it has a stricter limit, and needlessly
        # contending for the primary silo's slots for a write that
        # never touches it at all.
        write_limiter = self._adapter_mediator._write_limiter_for_silo(resolved_type_config["storage"]["silo"])
        with write_limiter.limit():
            return adapter.write_fields(
                object_type, object_id,
                _fields_to_columns(resolved_type_config, new_values),
                _fields_to_columns(resolved_type_config, expected_values),
                resolved_type_config,
            )

    def _create_object_with_limiter(self, object_type: str, adapter: "_ReadWriteAdapter",
                                     resolved_type_config: dict, values: dict) -> None:
        # THE create-side counterpart to _write_fields_with_limiter()
        # above -- was likewise duplicated at both places a create
        # group's row is actually inserted (_apply_one_create()'s
        # fresh-apply path, and _resume_one_create_entry()'s resume
        # path), identical shape at each.
        write_limiter = self._adapter_mediator._write_limiter_for_silo(resolved_type_config["storage"]["silo"])
        with write_limiter.limit():
            adapter.create_object(object_type, _fields_to_columns(resolved_type_config, values), resolved_type_config)

    def resume_pending_writes(self) -> dict:
        # Called ONCE, at deployment startup (see api/app.py / scripts/
        # run_deployment.py), before serving any real traffic -- the
        # "resume-on-startup" half of crash recovery write_log.py's own
        # module docstring names as this mechanism's next planned piece
        # of work. Scans EVERY still-INCOMPLETE batch (write_log.
        # get_pending_batches()) -- ALWAYS batches now, one sub_write
        # or many, since confirm_and_execute() always goes through
        # _apply_batch() (see that method's own docstring) -- and
        # walks each one's own sub_writes, resolving each via
        # _resume_one_batch() below.
        #
        # Naturally idempotent, safe to call more than once -- every
        # judgment is re-derived fresh from live backend state each
        # time; nothing here depends on a "have I already processed
        # this" flag anywhere. Deliberately STARTUP-TIME only, not a
        # continuously-running background process -- see write_log.py's
        # own module docstring for why periodic/continuous resume stays
        # a further, separately-scoped enhancement, not solved here.
        summary = {"resumed": 0, "already_applied": 0, "ambiguous": 0}
        for batch in self.write_log.get_pending_batches():
            object_refs = [(sw["object_type"], sw["object_id"]) for sw in batch["sub_writes"]]
            with self._adapter_mediator._locks_for_objects(object_refs):
                outcome = self._resume_one_batch(batch)
            # INVARIANT: every resume method returns one of exactly
            # three outcome names. There are five separate return sites
            # across three methods, all producing bare strings with
            # nothing enforcing the vocabulary -- a typo or a new
            # fourth outcome would otherwise surface as a bare KeyError
            # during crash recovery at startup, which is both the worst
            # moment and the least informative message. Naming the
            # offending value makes it immediately obvious what went
            # wrong.
            assert outcome in summary, (
                f"resume returned unknown outcome {outcome!r} -- "
                f"expected one of {sorted(summary)}"
            )
            summary[outcome] += 1
        return summary

    def _resume_one_batch(self, batch: dict) -> str:
        # Walks ONE incomplete batch's own sub_writes, each in one of
        # three states, determined via write_log.get_sub_write_entry():
        #   - No row exists yet -- the process crashed before even
        #     STARTING this sub_write. Applied fresh now, via the SAME
        #     _apply_one_update()/_apply_one_create() _apply_batch()
        #     itself calls -- resuming from nothing is, correctly,
        #     indistinguishable from a fresh apply that simply hadn't
        #     happened yet when the crash occurred.
        #   - Row exists, status='applied' -- already done; nothing to
        #     do.
        #   - Row exists, status='pending' -- genuinely crashed MID-
        #     apply on THIS specific sub_write. Handed off to the
        #     EXISTING, completely unchanged _resume_one_entry() --
        #     its own three-way per-storage-group classification
        #     (already applied / safe to apply / genuinely ambiguous)
        #     needs no knowledge of batches at all; a sub_write's own
        #     write_log row looks identical whether it's standalone or
        #     batch-owned.
        #
        # Returns "resumed" (at least one sub_write was freshly
        # applied or resumed here), "already_applied" (every sub_write
        # was already done), or "ambiguous" (at least one sub_write
        # left genuinely unresolved) -- the SAME three-way aggregation
        # _resume_one_update_entry() already uses one level down, for
        # storage GROUPS within one sub_write; this is the identical
        # principle one level up, for sub_writes within one batch. The
        # WHOLE batch stays 'pending' if even one sub_write is
        # ambiguous, so a caller reading OTHER, genuinely-resolved
        # objects in the SAME batch still sees correct, live data.
        any_applied_here = False
        any_ambiguous = False

        for sub_write_def in batch["sub_writes"]:
            object_type = sub_write_def["object_type"]
            object_id = sub_write_def["object_id"]
            existing_entry = self.write_log.get_sub_write_entry(batch["id"], object_type, object_id)

            if existing_entry is None:
                sub_write = SubWrite(
                    object_type, object_id, sub_write_def["operation"],
                    sub_write_def["changes"], sub_write_def["expected_current_values"],
                )
                if sub_write.operation == "update":
                    self._apply_one_update(sub_write, batch["id"], batch["user_id"], batch["description"])
                else:
                    self._apply_one_create(sub_write, batch["id"], batch["user_id"], batch["description"])
                any_applied_here = True
                continue

            if existing_entry["status"] == "applied":
                continue

            outcome = self._resume_one_entry(existing_entry)
            if outcome == "resumed":
                any_applied_here = True
            elif outcome == "ambiguous":
                any_ambiguous = True

        if any_ambiguous:
            return "ambiguous"
        self.write_log.mark_batch_applied(batch["id"])
        return "resumed" if any_applied_here else "already_applied"

    def _resume_one_entry(self, entry: dict) -> str:
        # Dispatches on operation -- an UPDATE entry's resume logic is
        # genuinely different from a CREATE entry's (three possible
        # outcomes per group vs two; see each method's own docstring
        # for why). resume_pending_writes() itself stays completely
        # unaware of the distinction, same per-object-locked call
        # either way.
        if entry["operation"] == "create":
            return self._resume_one_create_entry(entry)
        return self._resume_one_update_entry(entry)

    def _resume_one_update_entry(self, entry: dict) -> str:
        # Returns "resumed" (at least one group was freshly applied
        # here), "already_applied" (every group already matched the
        # intended new values -- nothing to apply), or "ambiguous" (at
        # least one group left genuinely unresolved).
        #
        # Per storage group, classifies live backend state into exactly
        # one of three outcomes, comparing the WHOLE group's fields
        # together (matching how they were WRITTEN together, in one
        # atomic SQL statement -- a partial match within one group
        # would mean something outside this system's own write path
        # touched it, not an ordinary crash):
        #   - matches the INTENDED new values -> already applied before
        #     the crash; nothing to do.
        #   - matches the ORIGINAL expected (pre-write) values -> never
        #     applied; safe to apply now, exactly as confirm_and_execute()
        #     would have.
        #   - matches NEITHER -> genuinely ambiguous. Something else
        #     touched this field between the crash and now (or the
        #     write's own precondition was already stale before the
        #     crash even happened). NEVER guessed at by overwriting
        #     either way -- logged via log_write_resume_ambiguous() for
        #     a human to resolve; this group's fields keep reporting the
        #     log's own intended value through get_field() (the same
        #     safe, degraded state as before recovery ran -- not worse).
        #
        # An entry is marked 'applied' only when EVERY group resolves
        # cleanly -- if even one group is ambiguous, the WHOLE entry
        # stays 'pending', so a caller reading OTHER, genuinely-resolved
        # fields on the SAME object still sees correct, live data (each
        # group is judged independently); only the specific ambiguous
        # field's own group keeps deferring to the log.
        object_type = entry["object_type"]
        object_id = entry["object_id"]
        groups = self._group_changes_by_storage(object_type, entry["changes"])
        any_applied_here = False
        any_ambiguous = False

        for adapter, resolved_type_config, group_changes in groups:
            group_expected = {
                field_name: entry["expected_current_values"][field_name]
                for field_name in group_changes
            }
            current_values = self._read_group_fields(object_type, object_id, adapter, resolved_type_config,
                                                       group_changes)

            if current_values == group_changes:
                continue  # already applied before the crash

            if current_values == group_expected:
                success = self._write_fields_with_limiter(
                    object_type, object_id, adapter, resolved_type_config, group_changes, group_expected,
                )
                if success:
                    any_applied_here = True
                    continue
                # A genuine race between our read just above and this
                # write -- something changed the row in between, outside
                # this per-object-locked sequence entirely (extremely
                # unlikely, but not impossible -- e.g. a direct write
                # against the backend from outside this system). Re-read
                # fresh rather than log the now-stale snapshot that made
                # us attempt the write in the first place.
                current_values = self._read_group_fields(object_type, object_id, adapter, resolved_type_config,
                                                           group_changes)
                if current_values == group_changes:
                    continue  # someone else applied it in the race window -- fine

            # Ambiguous: neither matched, from the start or after the
            # race-triggered re-read above. Log per-field, not per-group
            # -- a group can span several fields, and only some of them
            # may actually be the ones that don't match either value.
            any_ambiguous = True
            for field_name in group_changes:
                if current_values[field_name] not in (group_changes[field_name], group_expected[field_name]):
                    self.audit_log.log_write_resume_ambiguous(
                        entry["id"], object_type, object_id, field_name,
                        current_values[field_name], group_expected[field_name], group_changes[field_name],
                    )

        if any_ambiguous:
            return "ambiguous"
        self.write_log.mark_applied(entry["id"])
        return "resumed" if any_applied_here else "already_applied"

    def _resume_one_create_entry(self, entry: dict) -> str:
        # THE create-side counterpart to _resume_one_update_entry() --
        # genuinely SIMPLER: a storage group for a create has only TWO
        # possible states, not three -- the row either already exists
        # (already applied before the crash) or it doesn't (never
        # applied, safe to create now). There's no "ambiguous" case the
        # way update has: update's ambiguous case exists because a
        # field could hold some THIRD, pre-existing value neither the
        # old nor new state expected -- but a create has no "before"
        # state at all to be knocked off course like that. A genuine
        # collision (a row already existing under this id, from
        # entirely outside this system's own write path) surfaces as a
        # real INSERT constraint violation instead -- correctly failing
        # loud rather than silently guessing, matching the SPIRIT of
        # update's own ambiguous case (never overwrite blindly), just
        # enforced by the database itself here rather than by this
        # code's own comparison logic.
        #
        # Checks the type's own id_field specifically to decide "does
        # this row exist yet" -- not the full field set the way update
        # compares -- since a primary key is never legitimately NULL
        # for a real, existing row, regardless of what its OTHER
        # fields happen to be. Reading the full set back and comparing
        # it to entry["changes"] would have a genuine, if narrow, edge
        # case: a create whose group fields are ALL intentionally NULL
        # would look identical whether or not the row actually exists
        # yet. Checking the id specifically has no such ambiguity.
        object_type = entry["object_type"]
        object_id = entry["object_id"]
        id_field = self._adapter_mediator._type_schema(object_type)["id_field"]
        groups = self._group_changes_by_storage(object_type, entry["changes"])
        any_applied_here = False

        for adapter, resolved_type_config, group_changes in groups:
            id_column = get_column_for_field(resolved_type_config, id_field)
            existing_id = adapter.get_raw_field(object_type, object_id, id_column, resolved_type_config)
            if existing_id is not None:
                continue  # row already exists in this storage -- already applied

            group_with_id = {**group_changes, id_field: entry["changes"][id_field]}
            self._create_object_with_limiter(object_type, adapter, resolved_type_config, group_with_id)
            any_applied_here = True

        self.write_log.mark_applied(entry["id"])
        return "resumed" if any_applied_here else "already_applied"

    def visible_action_types(self, user_record: UserRecord) -> dict:
        # Mirrors DataMediator.visible_schema() exactly, for the SAME
        # reason: the model must never be shown an action it isn't
        # actually authorized to invoke. Filters self.action_types down
        # to exactly the ones this user holds an execute: grant for --
        # used by core/llm/agent_step_prompt.py to build the model-
        # facing action vocabulary, and by core/agent/agentic_loop.py's
        # run(), which computes this ONCE per request, same as
        # visible_schema() itself. Also the backend for GET /me/
        # visible-action-types (api/routes.py), Stage 3's own UI-facing
        # action discovery.
        #
        # discover:action_types -- a real, deliberate DEPARTURE from
        # this project's own earlier, more conservative default,
        # decided explicitly with the user after directly researching
        # Palantir's own real, documented behavior: by default, every
        # user with Ontology access sees every action type's own
        # title/description/rules, whether or not they can actually
        # execute it (verified directly against Palantir's real docs,
        # not assumed). A role holding this ONE, single, blanket grant
        # -- matching manage:users' own "not per-resource" shape, not
        # a new per-action-type discover:{name} vocabulary, since the
        # real use case (general orientation, understanding the full
        # business-process catalog) is a role-level decision, not an
        # action-by-action one -- sees the WHOLE catalog here,
        # regardless of which specific actions it can execute.
        #
        # execute: alone remains, unconditionally, the ONLY thing that
        # can ever actually authorize INVOKING an action --
        # propose_action() below enforces that itself, completely
        # unaffected by this method or this grant. A role could hold
        # discover:action_types and zero execute: grants at all, and
        # would correctly see every action's own shape here while
        # being unable to invoke a single one of them -- discovery and
        # execution are two genuinely separate axes, same as
        # Palantir's own real model keeps them.
        if authorize(user_record, self.roles, "discover:action_types"):
            return dict(self.action_types)
        return {
            action_name: action_def
            for action_name, action_def in self.action_types.items()
            if authorize(user_record, self.roles, f"execute:{action_name}")
        }

    def _read_current_state_for_criteria(self, object_type: str, object_id: Any,
                                          criteria: list[dict]) -> dict:
        # Fetches ONLY the fields "current_state" criteria actually
        # need -- read INDIVIDUALLY, one field at a time, rather than
        # batched through _resolve_shared_storage() the way `changes`
        # is. Deliberate: a criterion's own field may live in a
        # DIFFERENT storage than whatever's being written (e.g. a rule
        # about "status" while this write only touches "amount"), and
        # batching would incorrectly trigger the "cannot combine
        # fields from multiple storages" guard for two field sets that
        # were never meant to be resolved together in the first place.
        #
        # Uses DataMediator._read_field_with_log_check() -- the SAME
        # shared "check the write log first, else the real adapter"
        # merge get_field() and search_object() already use. Closes a
        # real, previously-stated gap: this used to read straight from
        # the adapter, meaning submission_criteria evaluation during a
        # NEW propose_action() call could evaluate against stale state
        # if the object already had a pending, unapplied edit from a
        # prior action (see write_log.py's own module docstring, which
        # used to name this exact limitation). Not mediator.get_field()
        # directly, though -- still a mechanical, internal check the
        # system makes on its own authority, not something gated by
        # the acting user's own field-level read grants.
        needed_fields = {c["field"] for c in criteria if c["check"] == "current_state"}
        current_state = {}
        for field_name in needed_fields:
            adapter, resolved_type_config = self._adapter_mediator._resolve_shared_storage(object_type, [field_name])
            current_state[field_name] = self._adapter_mediator._read_field_with_log_check(
                object_type, object_id, field_name, adapter, resolved_type_config
            )
        return current_state

    def _resolve_mutation_value(self, value_spec, parameters: dict, user_record: UserRecord):
        # A mutation's "value" is one of three kinds:
        #   - a LITERAL, used as-is
        #   - "parameter.<name>", a reference to one of the action's own
        #     declared parameters, resolved here at proposal time
        #   - "user.security_value", the ACTING user's own MAC value,
        #     substituted automatically -- NEVER model-supplied. This is
        #     the only safe way for a "create" action to set an object's
        #     security field: a literal would hardcode one tenant's
        #     value for every user; a parameter.<name> reference would
        #     let the model (or a hallucinated/injected value) choose
        #     ANY security value, including one that doesn't belong to
        #     the user actually authorized to perform this action.
        #     Discovered as a REAL, necessary gap while testing a
        #     "create" action end to end -- not a hypothetical: the
        #     INSERT itself failed (a real NOT NULL constraint on the
        #     security column) the moment a create action's mutations
        #     had no way to populate it safely at all.
        # Deliberately a small, fixed set of string-prefix conventions,
        # not a general expression language -- same reasoning as
        # submission_criteria's own fixed operator set (see that
        # module's docstring): a small, safe, easily-validated surface
        # rather than something that needs its own evaluator.
        if isinstance(value_spec, str) and value_spec.startswith("parameter."):
            param_name = value_spec[len("parameter."):]
            if param_name not in parameters:
                # Should be unreachable -- required-ness is validated
                # before mutations are ever resolved -- but a mutation
                # referencing a parameter that was never DECLARED at
                # all (a schema-authoring mistake, not a caller
                # mistake) would reach here. Fail loudly, not silently
                # substitute None.
                raise ValueError(f"Mutation references undeclared or missing parameter: {param_name!r}")
            return parameters[param_name]
        if value_spec == "user.security_value":
            return user_record.security_value
        return value_spec

    def _authorize_sub_write(self, user_record: UserRecord, object_type: str, object_id: Any,
                             operation: str, execute_action_id: str, rbac_allowed: bool) -> None:
        """MAC for one sub_write, audited, raising on refusal.

        A CREATE has no existing row for MAC to consult, so it passes
        on MAC grounds and is gated by RBAC alone -- the execute: grant
        is the whole check. Update and delete consult the object's
        security value the same way a read would.

        Extracted from propose_action() so its loop reads as its four
        concerns -- resolve, authorize, check criteria, build -- rather
        than as one 65-line body with cyclomatic complexity 26.
        """
        if operation == "create":
            mac_allowed = True
        else:
            mac_allowed = (
                user_record.security_value is not None
                and self._adapter_mediator._security_allowed(
                    object_type, object_id, user_record.security_value
                )
            )
        self.audit_log.log_access(
            user_record.user_id, object_type, object_id, execute_action_id,
            mac_allowed, rbac_allowed,
        )
        if not mac_allowed:
            raise PermissionError(f"{user_record.user_id!r} cannot modify this {object_type}")

    def _expected_current_values_for(self, operation: str, object_type: str, object_id: Any,
                                     changes: dict, action_type_name: str) -> dict:
        """What the row must still look like for this write to apply.

        Three operations, three answers. A DELETE expects nothing -- it
        goes through regardless of current values. An UPDATE reads
        every field it will change, so the lost-update check can
        confirm nobody moved it in between. A CREATE expects nothing
        either, but validates that its mutations set the id field and
        that the id agrees with the sub_write's own resolved object_id.
        """
        if operation == "delete":
            return {}
        if operation == "update":
            expected: dict = {}
            for adapter, resolved_type_config, group_changes in self._group_changes_by_storage(
                object_type, changes
            ):
                expected.update(
                    self._read_group_fields(object_type, object_id, adapter, resolved_type_config,
                                            group_changes)
                )
            return expected

        # create
        self._group_changes_by_storage(object_type, changes)
        id_field = self._adapter_mediator._type_schema(object_type)["id_field"]
        if id_field not in changes:
            raise ValueError(
                f"Create for {object_type!r} requires an explicit {id_field!r} value "
                f"in its own mutations -- auto-generated ids aren't supported"
            )
        if changes[id_field] != object_id:
            raise ValueError(
                f"Action {action_type_name!r}: sub_write's object_id resolved to "
                f"{object_id!r}, but its own mutations set {id_field!r} to "
                f"{changes[id_field]!r} -- these must match."
            )
        return {}

    def propose_action(self, user_record: UserRecord, action_type_name: str, parameters: dict) -> PendingWrite:
        # Matches Palantir Foundry's own action-type model directly
        # (verified against their docs, not assumed): a NAMED,
        # independently-governed operation, not a generic CRUD verb.
        # The object(s) being acted on are always just PARAMETERS too
        # -- "an existing object whose primary key is derived from
        # object reference parameters," Palantir's own words -- never
        # a separate, out-of-band argument the way object_id used to
        # be here. See SubWrite's and core/ontology/action_types.py's
        # own docstrings for the full reasoning behind that change.
        #
        # RBAC is ACTION-level, deliberately NOT a field-grant hybrid --
        # one "execute:{action_type_name}" grant, not one write:{type}.
        # {field} grant per field the action's mutations happen to
        # touch, AS LONG AS every sub_write targets the SAME object
        # type. This is CLOSER to Palantir's real model and easier for
        # whoever is actually configuring roles to reason about ("this
        # role may perform this named business operation," not "this
        # role may touch these raw columns") -- but it means a role's
        # true field-level reach is now defined by whatever an action's
        # mutations happen to declare, not by an independent, per-field
        # decision. Editing an action's mutations later is therefore a
        # REAL grant-equivalent decision, not routine schema
        # maintenance -- every role already holding execute: on that
        # action silently gains whatever new mutation was added. Once
        # sub_writes spans more than one DISTINCT object type, that
        # risk stops being bounded to "new fields on the same type" --
        # see the cross-type RBAC check further below for how this is
        # actually contained.
        action_def = self.action_types.get(action_type_name)
        if action_def is None:
            raise ValueError(f"Unknown action_type: {action_type_name!r}")

        execute_action_id = f"execute:{action_type_name}"
        rbac_allowed = authorize(user_record, self.roles, execute_action_id)
        if not rbac_allowed:
            # Logged ONCE here, with mac_allowed=None -- MAC never ran,
            # short-circuited before a real database query. Uses
            # action_type_name itself, not any object_type -- this
            # check is about whether the user may invoke this ACTION
            # at all, before WHICH object(s) it touches is even known;
            # every action, single- or multi-object, shares this same
            # first gate, and there is no single object_type to report
            # here regardless.
            self.audit_log.log_access(
                user_record.user_id, action_type_name, None, execute_action_id,
                mac_allowed=None, rbac_allowed=False,
            )
            raise PermissionError(f"{user_record.user_id!r} is not authorized for: {execute_action_id!r}")

        # Parameter validation -- MOVED before per-sub_write MAC below
        # (was after, back when object_id was a directly-supplied,
        # separate argument known independent of parameters). Every
        # sub_write's own identity now comes FROM parameters, so
        # parameters must be validated before any sub_write's object_id
        # can even be resolved, let alone MAC-checked. REQUIRED
        # parameters must be present; UNDECLARED ones are rejected
        # outright, not silently ignored -- "explicit and safe,"
        # matching this project's own consistent discipline.
        declared_params = action_def.get("parameters", {})
        for param_name, param_spec in declared_params.items():
            if param_spec.get("required") and param_name not in parameters:
                raise ValueError(f"Missing required parameter {param_name!r} for action {action_type_name!r}")
        unknown_params = set(parameters) - set(declared_params)
        if unknown_params:
            raise ValueError(
                f"Unknown parameter(s) for action {action_type_name!r}: {sorted(unknown_params)}"
            )

        sub_write_defs = action_def["sub_writes"]

        # Cross-type RBAC -- the OPTION B decision. execute: alone is
        # sufficient only when every sub_write targets the SAME object
        # type (unchanged from before sub_writes existed at all). The
        # moment sub_writes spans two or more DISTINCT types, every one
        # of those types additionally needs its own write:<Type>.
        # {field} grant, for each field that type's own mutations
        # touch -- checked here, before anything is resolved or
        # logged, same fail-closed timing as the execute: check above.
        # Deliberately no exemption for any "first" or "primary" type
        # -- sub_writes has no inherent ordering that could principled
        # single one out, and a role trusted with execute: on a
        # cross-type action has no more inherent reason to be trusted
        # with EVERY type it touches than with any one of them.
        affected_types = {sw["object_type"] for sw in sub_write_defs}
        if len(affected_types) > 1:
            for sw_def in sub_write_defs:
                for mutation in sw_def["mutations"]:
                    write_action_id = f"write:{sw_def['object_type']}.{mutation['set']['property']}"
                    if not authorize(user_record, self.roles, write_action_id):
                        raise PermissionError(
                            f"{user_record.user_id!r} is not authorized for: {write_action_id!r} "
                            f"(required because {action_type_name!r} touches more than one object type)"
                        )

        # Resolve, MAC-check, and validate EACH sub_write independently.
        resolved_sub_writes = []
        seen_object_refs: set[tuple[str, str]] = set()
        for sw_def in sub_write_defs:
            object_type = sw_def["object_type"]
            operation = sw_def["operation"]

            # The object's own identity, resolved FIRST, via the SAME
            # _resolve_mutation_value() vocabulary every mutation value
            # already uses -- see this method's own top-level comment
            # for why object_id is just an ordinary parameter now, not
            # a special case.
            object_id = self._resolve_mutation_value(sw_def["object_id"], parameters, user_record)

            # The FULL duplicate check, against REAL resolved ids --
            # the complement to core/ontology/action_types.py's own,
            # WEAKER, load-time-only structural check. Two DIFFERENT
            # object_id expressions (e.g. parameter.from_id and
            # parameter.to_id) could still resolve to the SAME real id
            # once real parameters arrive -- the schema-load check can
            # never catch that; only this, with real values in hand,
            # can.
            object_ref = (object_type, str(object_id))
            if object_ref in seen_object_refs:
                raise ValueError(
                    f"Action {action_type_name!r}: two sub_writes both resolved to the "
                    f"identical {object_type} {object_id!r}"
                )
            seen_object_refs.add(object_ref)

            self._authorize_sub_write(
                user_record, object_type, object_id, operation, execute_action_id, rbac_allowed
            )

            # Submission criteria -- now PER SUB_WRITE, not per action;
            # see core/ontology/submission_criteria.py's own docstring
            # for why this stays a property of the write being
            # proposed, not a generic validation bolted onto "update"
            # itself. The "parameter" check kind still reads from the
            # action's own declared parameter names, shared across
            # every sub_write, not a per-sub_write namespace.
            criteria = sw_def.get("submission_criteria", [])
            if criteria:
                current_state = self._read_current_state_for_criteria(object_type, object_id, criteria) \
                    if operation == "update" else None
                evaluate_submission_criteria(criteria, current_state, parameters)

            # Resolve this sub_write's own declared mutations into a
            # concrete field-value dict -- this, not free-form model
            # input, is what actually gets written.
            # A DELETE HAS NO MUTATIONS. Validation has allowed that
            # since deletes were added -- a delete names an object, not
            # a change to it -- but this path still required the key,
            # so a delete action validated cleanly at load and raised
            # KeyError the moment an agent proposed one.
            #
            # Each half was tested and the SEAM between them was not,
            # which is what the end-to-end test that found this exists
            # for.
            changes = {
                mutation["set"]["property"]: self._resolve_mutation_value(mutation["set"]["value"],
                                                                            parameters, user_record)
                for mutation in (sw_def.get("mutations") or [])
            }

            # For "update," expected_current_values is built PER
            # STORAGE GROUP (same _group_changes_by_storage()
            # confirm_and_execute() itself uses) -- this is what makes
            # a multi-storage update possible at all; see write_log.py's
            # own module docstring for the full mechanism.
            expected_current_values = self._expected_current_values_for(
                operation, object_type, object_id, changes, action_type_name
            )
            resolved_sub_writes.append(SubWrite(object_type, object_id, operation, changes, expected_current_values))

        description = f"{action_type_name}(parameters={parameters})"
        return PendingWrite(tuple(resolved_sub_writes), user_record.user_id, description, action_type_name)

    def confirm_and_execute(self, pending: PendingWrite, approved: bool) -> dict | None:
        # ALWAYS goes through _apply_batch() below, one sub_write or
        # many -- see this file's own AI-notes at the bottom, and
        # write_log.py's own MULTI-OBJECT BATCHES docstring section,
        # for why: uniform REPRESENTATION (a write_log_batches row
        # exists for every write, not just multi-object ones) is what
        # lets the CODE stay genuinely branch-free, the same way
        # _group_changes_by_storage() already lets a single-storage
        # object apply through the exact same loop as a multi-storage
        # one, with no special case for either.
        request_id = str(uuid.uuid4())
        self.audit_log.log_pre(
            request_id, pending.user_id, pending.description, f"write:{pending.action_type_name}",
            {
                # An explicit, computed field stating what happened,
                # not something a reader has to infer by counting --
                # same "explicit signal, not implicit inference"
                # principle log_access() already follows by reporting
                # mac_allowed/rbac_allowed independently rather than
                # only a combined allow/deny bit.
                "sub_write_count": len(pending.sub_writes),
                "sub_writes": [
                    {"object_type": sw.object_type, "object_id": sw.object_id, "changes": sw.changes}
                    for sw in pending.sub_writes
                ],
            },
            approved,
        )

        if not approved:
            return None

        object_ids = self._apply_batch(pending)
        self.audit_log.log_post(request_id, "success", object_ids)
        return {"status": "written", "object_ids": object_ids}

    def _apply_batch(self, pending: PendingWrite) -> list:
        # THE actual atomicity boundary for the WHOLE write, one
        # sub_write or many -- see write_log.py's own MULTI-OBJECT
        # BATCHES docstring section for the full mechanism this
        # implements: log the batch's COMPLETE, already-resolved intent
        # FIRST (trivially atomic, one INSERT, regardless of how many
        # sub_writes it describes), THEN apply each sub_write's own
        # share SEQUENTIALLY, in the batch's own declared LIST order
        # (referential correctness -- a sub_write creating an object
        # must apply before another sub_write that references it),
        # THEN mark the whole batch applied.
        #
        # Locks for EVERY object in this batch, acquired ONCE, up
        # front, in SORTED order (deadlock avoidance -- see
        # DataMediator._locks_for_objects()'s own docstring), held for
        # the WHOLE sequence, released together at the end -- NOT
        # acquired per-sub_write inside the loop below. This is why
        # _apply_one_update()/_apply_one_create() below no longer
        # acquire their own lock the way the pre-batch
        # _apply_update_via_log()/_apply_create_via_log() used to:
        # threading.Lock is not reentrant, so acquiring the SAME
        # object's lock twice from the same thread (once here, once
        # again inside a per-sub_write helper) would deadlock outright,
        # not just be redundant.
        object_refs = [(sw.object_type, sw.object_id) for sw in pending.sub_writes]
        with self._adapter_mediator._locks_for_objects(object_refs):
            batch_id = self.write_log.log_pending_batch(
                [
                    {
                        "object_type": sw.object_type, "object_id": sw.object_id, "operation": sw.operation,
                        "changes": sw.changes, "expected_current_values": sw.expected_current_values,
                    }
                    for sw in pending.sub_writes
                ],
                pending.user_id, pending.description,
            )

            object_ids: list[Any] = []
            try:
                for sub_write in pending.sub_writes:
                    if sub_write.operation == "delete":
                        object_ids.append(
                            self._apply_one_delete(
                                sub_write, batch_id, pending.user_id, pending.description
                            )
                        )
                    elif sub_write.operation == "update":
                        object_ids.append(
                            self._apply_one_update(
                                sub_write, batch_id, pending.user_id, pending.description,
                                batch_already_committed=bool(object_ids),
                            )
                        )
                    else:
                        object_ids.append(
                            self._apply_one_create(sub_write, batch_id, pending.user_id, pending.description)
                        )
            except Exception:
                # A REAL, confirmed bug this closes, found by running two
                # genuinely concurrent confirm_and_execute() calls against
                # the same account for the first time (see tests/unit/
                # test_write_path_concurrency.py).
                #
                # The common cause is the optimistic-concurrency check
                # correctly REJECTING this write because another caller
                # changed the object first. That rejection is right. What
                # was wrong is what it left behind: the batch was already
                # logged as pending, so the exception propagated with the
                # batch still marked pending forever.
                #
                # That is not a cosmetic leak. resume_pending_writes()
                # runs unguarded at startup (api/app.py's own create_app())
                # and would find this batch, try to re-apply it, hit the
                # SAME stale-value check, and raise -- so a single rejected
                # concurrent write would prevent the server from starting
                # again. Confirmed directly, not reasoned about.
                #
                # Marking it applied is the correct resolution when NOTHING
                # applied: there is genuinely nothing for recovery to
                # finish. A PARTIAL failure is deliberately left pending
                # instead -- that is exactly the state crash recovery
                # exists to reconcile, and abandoning it would strand a
                # half-written batch.
                if not object_ids:
                    self.write_log.mark_batch_applied(batch_id)
                raise

            # INVARIANT: a batch is only marked applied when every one
            # of its sub-writes produced a real object id. If these ever
            # diverge, the batch is being recorded as complete while
            # part of it never ran -- the exact corruption Point 2 of
            # the machinery audit found and fixed, where crash recovery
            # then skips a write that never happened. Asserted rather
            # than commented because a silent divergence here is
            # unrecoverable: once marked applied, nothing ever revisits
            # it.
            assert len(object_ids) == len(pending.sub_writes) and all(
                object_id is not None for object_id in object_ids
            ), (
                f"batch {batch_id} marking applied with {len(object_ids)} of "
                f"{len(pending.sub_writes)} sub-writes done, ids={object_ids}"
            )
            self.write_log.mark_batch_applied(batch_id)

        return object_ids

    def _apply_one_update(self, sub_write: SubWrite, batch_id: str, user_id: str, description: str,
                           batch_already_committed: bool = False) -> Any:
        # ONE sub_write's own share of a (possibly multi-object) batch
        # -- see _apply_batch() above for the locking and batch-logging
        # this is always called from within, and for why this no
        # longer acquires its own per-object lock the way the pre-
        # batch _apply_update_via_log() used to. Logs this ONE sub_
        # write's own write_log row, batch_id set, THEN applies each
        # storage's own share of the mutations SEQUENTIALLY (same
        # _group_changes_by_storage() mechanism as before -- a single-
        # group `groups` list is simply the degenerate case), THEN
        # marks this row applied.
        log_id = self.write_log.log_pending_update(
            sub_write.object_type, sub_write.object_id,
            sub_write.changes, sub_write.expected_current_values,
            user_id, description, batch_id=batch_id,
        )

        groups = self._group_changes_by_storage(sub_write.object_type, sub_write.changes)
        # Tracks whether any storage group has already COMMITTED, which
        # decides what a later failure means: nothing applied yet is a
        # clean rejection to abandon, whereas a partially-applied entry
        # must stay pending for crash recovery to reconcile.
        applied_groups = 0
        for adapter, resolved_type_config, group_changes in groups:
            group_expected = {
                field_name: sub_write.expected_current_values[field_name]
                for field_name in group_changes
            }
            success = self._write_fields_with_limiter(
                sub_write.object_type, sub_write.object_id, adapter, resolved_type_config,
                group_changes, group_expected,
            )
            if not success:
                # NOTHING in this entry committed, so the log row is
                # abandoned rather than left pending. Without this, a
                # rejected write leaves a row that get_field()'s own
                # write-log masking keeps reporting as the object's
                # value -- a read showing a number that was never
                # written, indefinitely. Found by running two genuinely
                # concurrent writes for the first time (see tests/unit/
                # test_write_path_concurrency.py); previously recorded
                # as a known limitation, now closed for the case where
                # it is unambiguously safe to close.
                #
                # DELIBERATELY only when applied_groups is empty. If an
                # EARLIER group already committed, this entry describes
                # a genuinely half-applied write, and that is precisely
                # what crash recovery exists to reconcile -- abandoning
                # it would strand the applied half with no record.
                # Abandoned ONLY when this write changed nothing AND
                # nothing earlier in the same batch did either. A
                # multi-object action whose FIRST sub-write already
                # committed is genuinely half-applied: marking this row
                # applied would tell crash recovery there is nothing to
                # reconcile, stranding the mismatch permanently and
                # leaving get_field() masking a value that will never
                # exist. That state must stay pending -- see
                # _apply_batch()'s own handling.
                if not applied_groups and not batch_already_committed:
                    self.write_log.mark_applied(log_id)
                raise ValueError(
                    f"{sub_write.object_type} {sub_write.object_id!r} changed since this "
                    f"write was proposed -- refresh and retry"
                )
            applied_groups += 1

        # INVARIANT: every storage group committed before this row is
        # marked applied. An MDO object spans several physical tables,
        # and marking the row applied with only some of them written
        # would leave get_field() reporting the unwritten ones as
        # updated -- a read showing a value that does not exist, with
        # nothing left pending for recovery to notice.
        assert applied_groups == len(groups), (
            f"{sub_write.object_type} {sub_write.object_id!r}: marking applied with "
            f"{applied_groups} of {len(groups)} storage groups written"
        )
        self.write_log.mark_applied(log_id)

        # LAST EDIT WINS: a write after a delete makes the object
        # visible again, so the derived index must drop it -- the same
        # rule Foundry's own indexing uses ("most recent update wins").
        # Unconditional rather than guarded by a lookup: clearing an
        # object that was never deleted is a no-op, and a lookup on
        # every write would cost more than the clear it avoids.
        self.write_log.clear_delete(sub_write.object_type, sub_write.object_id)
        return sub_write.object_id

    def _apply_one_delete(self, sub_write: SubWrite, batch_id: str, user_id: str,
                           description: str) -> Any:
        """Records a delete. Writes NOTHING to the customer's database.

        Following Foundry directly: a delete there is an EDIT, written
        to the writeback layer rather than the backing datasource, so
        "users have access to both the original data and the edited
        data." Their resolution rule is that when an object's latest
        edit is a delete it "is not visible in the ontology, regardless
        of whether any corresponding row is in one of the data
        sources."

        Three real consequences follow, and all of them are why this is
        the right model here rather than a compromise:
          - Elysium's external read-only guarantee stays intact. We
            never destroy a row we do not own.
          - The delete is REVERSIBLE. A later create for the same id
            wins, because the read path takes the latest applied
            operation.
          - Crash recovery is trivial where a destructive delete would
            be genuinely ambiguous. A missing row cannot tell you
            whether YOUR delete succeeded, someone else's did, or it
            never existed -- but this record lives in storage this
            project owns and can simply be read.

        Marked applied immediately, because writing the log entry IS
        the whole operation. There is no second step that could fail
        partway.
        """
        log_id = self.write_log.log_pending_update(
            sub_write.object_type, sub_write.object_id,
            {}, sub_write.expected_current_values,
            user_id, description, batch_id=batch_id, operation="delete",
        )
        self.write_log.mark_applied(log_id)

        # The DERIVED INDEX, updated as part of applying the delete.
        # Reads consult this rather than resolving deleted-ness by
        # scanning the log, which cost 47.2 ms per search at 55,000
        # log rows and grew with edit history forever.
        #
        # The log entry is written FIRST and is the authority. If the
        # process dies between these two, the index is stale but
        # RECOVERABLE -- rebuild_deleted_index() regenerates it from
        # the log. The reverse order would leave an index entry with
        # no log record behind it, which nothing could reconcile.
        self.write_log.record_delete(
            sub_write.object_type, sub_write.object_id, log_id
        )
        return sub_write.object_id

    def _apply_one_create(self, sub_write: SubWrite, batch_id: str, user_id: str, description: str) -> Any:
        # THE create-side counterpart to _apply_one_update() above --
        # see write_log.py's own module docstring for the shared
        # mechanism, and _apply_batch() above for the locking and
        # batch-logging this is always called from within. Requires
        # sub_write.changes to already include the type's own id_field,
        # explicitly -- propose_action() enforces this upfront; matches
        # Palantir Foundry's own MDO requirement that an object's
        # primary key already exist, matching, in every backing
        # datasource (verified directly, not assumed -- see
        # https://www.palantir.com/docs/foundry/object-permissioning/multi-datasource-objects).
        id_field = self._adapter_mediator._type_schema(sub_write.object_type)["id_field"]
        log_id = self.write_log.log_pending_create(
            sub_write.object_type, sub_write.object_id,
            sub_write.changes, user_id, description, batch_id=batch_id,
        )

        groups = self._group_changes_by_storage(sub_write.object_type, sub_write.changes)
        for adapter, resolved_type_config, group_changes in groups:
            # Every group's own row needs the id as one of its actual
            # inserted columns -- unlike update, create_object() has no
            # separate object_id parameter for a WHERE clause; the id
            # is just another field being inserted, into EVERY
            # storage, not just whichever ONE group's mutations
            # happened to place it in naturally (a no-op overwrite for
            # that one group, a real injection for every other).
            group_with_id = {**group_changes, id_field: sub_write.object_id}
            self._create_object_with_limiter(sub_write.object_type, adapter, resolved_type_config, group_with_id)

        self.write_log.mark_applied(log_id)
        return sub_write.object_id
