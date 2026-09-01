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
from typing import Any, Literal

from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import UserRecord, authorize
from core.ontology.interface import DataSiloAdapter
from core.ontology.mediator import DataMediator
from core.ontology.schema import get_column_for_field
from core.ontology.submission_criteria import evaluate_submission_criteria
from core.ontology.write_log import WriteLog


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
    operation: Literal["update", "create"]
    changes: dict
    expected_current_values: dict = field(default_factory=dict)  # for update lost-update checks


@dataclass(frozen=True)
class PendingWrite:
    # sub_writes is ALWAYS at least one entry, even for what looks like
    # an ordinary single-object action -- there is deliberately no
    # separate "single-object" representation living alongside a
    # "multi-object" one. propose_action() and core/ontology/
    # action_types.py's own schema-load validation already fully
    # support declaring and resolving more than one -- the one piece
    # still catching up is confirm_and_execute()'s own apply logic
    # (still only ever applies sub_writes[0] as of this writing; see
    # this file's own AI-notes at the bottom for exactly where that
    # stands).
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
    def __init__(self, mediator: DataMediator, roles: dict, action_types: dict):
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

    @property
    def write_log(self) -> WriteLog:
        # Always the SAME instance self.mediator itself holds -- never
        # a separately-stored copy, so there is nothing here that could
        # ever drift out of sync with it.
        #
        # The assert below is a type-narrowing hint for mypy only, not
        # the real runtime guard -- mediator.write_log is typed
        # WriteLog | None (genuinely optional on DataMediator itself,
        # see its own docstring), but this class's own __init__ already
        # raises a real, non-stripped ValueError if it were None,
        # before a WriteMediator claiming this property exists at all.
        # mypy can't trace that guarantee across to a different
        # object's attribute, so it's restated here, in the one place
        # that needs it, rather than loosening this property's own
        # return type for every caller.
        assert self.mediator.write_log is not None
        return self.mediator.write_log

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
            adapter, resolved_type_config = self.mediator._resolve_shared_storage(object_type, [field_name])
            key = id(resolved_type_config["storage"])
            if key not in groups:
                groups[key] = (adapter, resolved_type_config, {})
            groups[key][2][field_name] = changes[field_name]
        return list(groups.values())

    def _read_group_fields(self, object_type: str, object_id: Any, adapter: DataSiloAdapter,
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

    def _write_fields_with_limiter(self, object_type: str, object_id: Any, adapter: DataSiloAdapter,
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
        write_limiter = self.mediator._write_limiter_for_silo(resolved_type_config["storage"]["silo"])
        with write_limiter.limit():
            return adapter.write_fields(
                object_type, object_id,
                _fields_to_columns(resolved_type_config, new_values),
                _fields_to_columns(resolved_type_config, expected_values),
                resolved_type_config,
            )

    def _create_object_with_limiter(self, object_type: str, adapter: DataSiloAdapter,
                                     resolved_type_config: dict, values: dict) -> None:
        # THE create-side counterpart to _write_fields_with_limiter()
        # above -- was likewise duplicated at both places a create
        # group's row is actually inserted (_apply_one_create()'s
        # fresh-apply path, and _resume_one_create_entry()'s resume
        # path), identical shape at each.
        write_limiter = self.mediator._write_limiter_for_silo(resolved_type_config["storage"]["silo"])
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
            with self.mediator._locks_for_objects(object_refs):
                outcome = self._resume_one_batch(batch)
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
        id_field = self.mediator._type_schema(object_type)["id_field"]
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
            adapter, resolved_type_config = self.mediator._resolve_shared_storage(object_type, [field_name])
            current_state[field_name] = self.mediator._read_field_with_log_check(
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

            if operation == "create":
                mac_allowed = True
            else:
                mac_allowed = (
                    user_record.security_value is not None
                    and self.mediator._security_allowed(object_type, object_id, user_record.security_value)
                )
            self.audit_log.log_access(user_record.user_id, object_type, object_id, execute_action_id,
                                       mac_allowed, rbac_allowed)
            if not mac_allowed:
                raise PermissionError(f"{user_record.user_id!r} cannot modify this {object_type}")

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
            changes = {
                mutation["set"]["property"]: self._resolve_mutation_value(mutation["set"]["value"],
                                                                            parameters, user_record)
                for mutation in sw_def["mutations"]
            }

            # For "update," expected_current_values is built PER
            # STORAGE GROUP (same _group_changes_by_storage()
            # confirm_and_execute() itself uses) -- this is what makes
            # a multi-storage update possible at all; see write_log.py's
            # own module docstring for the full mechanism.
            if operation == "update":
                expected_current_values = {}
                for adapter, resolved_type_config, group_changes in self._group_changes_by_storage(
                    object_type, changes
                ):
                    expected_current_values.update(
                        self._read_group_fields(object_type, object_id, adapter, resolved_type_config, group_changes)
                    )
            else:
                # _group_changes_by_storage() also validates every
                # field name is real -- an unknown field in a create's
                # mutations should fail HERE, at proposal time, not
                # later at confirm_and_execute() time after a human may
                # have already approved it. An explicit id is ALWAYS
                # required, matching update's own precedent of a
                # SINGLE, unified path regardless of storage count --
                # auto-generated ids aren't supported at all: the
                # log-first-then-apply ordering this whole mechanism
                # depends on needs the id known BEFORE any storage is
                # touched, and an auto-generated id, by definition,
                # isn't known until AFTER an INSERT already ran.
                # Matches Palantir Foundry's own MDO requirement that a
                # primary key already exist, matching, in every backing
                # datasource.
                self._group_changes_by_storage(object_type, changes)
                id_field = self.mediator._type_schema(object_type)["id_field"]
                if id_field not in changes:
                    raise ValueError(
                        f"Create for {object_type!r} requires an explicit {id_field!r} value "
                        f"in its own mutations -- auto-generated ids aren't supported"
                    )
                if changes[id_field] != object_id:
                    # A real, previously-impossible-to-catch authoring
                    # mistake -- this sub_write's own object_id
                    # expression disagrees with what its OWN mutations
                    # separately set for the type's id_field. Both
                    # exist for a reason (object_id: resolved
                    # uniformly, up front, for MAC/locking/duplicate-
                    # checking, matching every other sub_write
                    # regardless of operation; changes[id_field]: the
                    # real value that actually gets inserted) -- if
                    # they ever disagree, something in the schema is
                    # wrong, and this is the one place both are known
                    # at once to catch it.
                    raise ValueError(
                        f"Action {action_type_name!r}: sub_write's object_id resolved to "
                        f"{object_id!r}, but its own mutations set {id_field!r} to "
                        f"{changes[id_field]!r} -- these must match."
                    )
                expected_current_values = {}

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
        with self.mediator._locks_for_objects(object_refs):
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

            object_ids = []
            for sub_write in pending.sub_writes:
                if sub_write.operation == "update":
                    object_ids.append(self._apply_one_update(sub_write, batch_id, pending.user_id, pending.description))
                else:
                    object_ids.append(self._apply_one_create(sub_write, batch_id, pending.user_id, pending.description))

            self.write_log.mark_batch_applied(batch_id)

        return object_ids

    def _apply_one_update(self, sub_write: SubWrite, batch_id: str, user_id: str, description: str) -> Any:
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
                # See write_log.py's own docstring for the known,
                # stated limitation this leaves: if an EARLIER group
                # already committed successfully before this one
                # failed, the log entry stays 'pending' indefinitely,
                # and get_field() will keep reporting the LATER
                # group's field as updated even though it never was --
                # deferred, folded into the same crash-recovery work
                # rather than solved separately here.
                raise ValueError(
                    f"{sub_write.object_type} {sub_write.object_id!r} changed since this "
                    f"write was proposed -- refresh and retry"
                )

        self.write_log.mark_applied(log_id)
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
        id_field = self.mediator._type_schema(sub_write.object_type)["id_field"]
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


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history -- was previously the URGENT / read-this-
# first item):
# - resume_pending_writes() was NOT rebuilt for the "always batch"
#   world confirm_and_execute()/_apply_batch() moved to -- it used to
#   scan ONLY write_log.get_pending_entries() (batch_id IS NULL),
#   which meant it silently found nothing for any real, confirm_and_
#   execute()-originated crash. NOW FIXED: resume_pending_writes()
#   scans write_log.get_pending_batches() and walks each incomplete
#   batch's own sub_writes via the new _resume_one_batch(), using
#   write_log.get_sub_write_entry() for the per-sub-write three-way
#   dispatch (never started / mid-apply / already done) exactly as
#   originally designed below. get_pending_entries() itself is
#   RETIRED entirely (see write_log.py's own docstring) -- replaced by
#   get_all_pending_writes() (for DataMediator._reconcile_search_
#   with_pending_writes(), which had the IDENTICAL silent-no-op bug,
#   found and fixed at the same time, not a separate issue) and
#   get_sub_write_entry() (for resume's own per-sub-write lookup).
#   Full new test coverage: tests/unit/test_write_log_resume.py
#   (rebuilt, including two genuinely new tests: a sub-write that
#   never even started, and the first test in this whole effort
#   exercising two real, different objects within one batch) and
#   tests/unit/test_write_log_create.py's own resume tests (rebuilt
#   the same way, create-side).
#
# RESOLVED (kept for history):
# - TransferFunds (tests/integration/fixtures/ontology_schema.yaml) is
#   the real, deliberately-authored multi-object action_type this note
#   used to call for -- a real fund transfer, two sub_writes, both
#   Account, same-type (execute:-only RBAC, not the cross-type write:
#   path -- that's still only proven synthetically, by this file's own
#   unit tests, which remains fine: nothing about same-type vs cross-
#   type changes how propose_action() itself resolves or applies a
#   sub_write). tests/unit/test_transfer_funds.py is the fully
#   scripted, real-schema proof (propose_action() called directly, no
#   model); tests/integration/test_transfer_funds_e2e.py is the real-
#   Ollama proof, mirroring test_named_actions_e2e.py's own structure
#   -- CONFIRMED passing against a real model (see that file's own
#   AI-notes for the full real-run record, including a genuine, real
#   transcript of a model independently gathering both accounts'
#   current balances before correctly proposing a two-object write).
#   Found and fixed, while building this: the resolved-id duplicate
#   check in THIS file (the "seen_object_refs" logic a few hundred
#   lines up) had NO test coverage anywhere in the project until now --
#   only the weaker, load-time structural check (core/ontology/
#   action_types.py) was ever exercised.
#
# REJECTED ALTERNATIVES (considered and ruled out -- don't re-propose
# without reading why):
# - Creating a write_log_batches row ONLY when len(sub_writes) > 1
#   (skip it for the single-object case, keep the old, batch-free
#   direct path for that case specifically) was seriously considered
#   and explicitly rejected, after real back-and-forth with the user.
#   The rejected reasoning: it looked like uniform CODE (no branch in
#   the apply logic) but wasn't uniform REPRESENTATION -- every reader
#   of write_log/write_log_batches (get_pending_changes(), a future
#   admin audit viewer, resume) would still need to know and handle
#   "sometimes there's a batch row, sometimes there isn't" as a real
#   distinction. The MDO precedent (_group_changes_by_storage() always
#   produces at least one group, never a special "single-storage, no
#   grouping" path) is what settled this: uniform representation is
#   what LETS the code have no branch anywhere, not the other way
#   around. The accepted cost -- one extra INSERT and one extra UPDATE
#   per write, forever, even for the overwhelmingly common single-
#   object case -- was judged worth it, consistent with every other
#   uniformity trade-off made this same session (the sub_writes YAML
#   shape, object_id's full retirement, the object_ids-always-a-list
#   API response).
# - Palantir's OWN real architecture (a separate Funnel queue plus a
#   live, always-current index, with the real backing dataset lagging
#   behind via periodic/triggered flush) was researched directly and
#   deliberately NOT built here -- see write_log.py's own AI-notes
#   (once it has this same section) for the full reasoning: the
#   GUARANTEE matches (no reader ever sees a torn multi-object state),
#   the MECHANISM is a simpler analog suited to this project's much
#   smaller, single-process scale. Palantir's own "a single
#   modification instruction, always, regardless of object count" was
#   real, direct confirmation FOR the always-batch decision above,
#   even though the underlying machinery differs.
#
# KNOWN LIMITATIONS:
# - log_pre()'s own audit entry now embeds every sub_write's full
#   changes dict, for every write -- a real, if usually small, size
#   increase per audit entry compared to the old, single-object-only
#   shape, bounded by MAX_SUB_WRITES (core/ontology/action_types.py)
#   at 20. Not expected to matter at this project's scale; worth
#   knowing if audit log size or write throughput are ever profiled
#   and this shows up.
