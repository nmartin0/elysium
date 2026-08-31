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
class PendingWrite:
    object_type: str
    object_id: Any | None
    action: Literal["update", "create"]
    changes: dict
    user_id: str
    description: str
    expected_current_values: dict = field(default_factory=dict)  # for update lost-update checks


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
        # _apply_update_via_log(), and the resume path in
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
        # group's row is actually inserted (_apply_create_via_log()'s
        # fresh-apply path, and _resume_one_create_entry()'s resume
        # path), identical shape at each.
        write_limiter = self.mediator._write_limiter_for_silo(resolved_type_config["storage"]["silo"])
        with write_limiter.limit():
            adapter.create_object(object_type, _fields_to_columns(resolved_type_config, values), resolved_type_config)

    def _apply_update_via_log(self, pending: PendingWrite) -> Any:
        # THE actual atomicity boundary -- see write_log.py's own
        # module docstring for the full mechanism and its current,
        # deliberate scope boundary (update only; crash recovery and
        # partial-failure reconciliation both explicitly deferred).
        # Logs ONE row (trivially atomic regardless of how many
        # storages pending.changes spans), THEN applies each storage's
        # own share of the mutations SEQUENTIALLY, THEN marks the
        # entry applied.
        #
        # The per-object lock is held across the WHOLE sequence -- not
        # just the apply portion -- so a second, concurrent write to
        # the SAME object can never see this entry as anything other
        # than fully absent or fully applied; write_log.
        # get_pending_changes()'s own "at most one pending entry per
        # object" assumption depends on this holding.
        object_lock = self.mediator._lock_for_object(pending.object_type, pending.object_id)
        with object_lock:
            log_id = self.write_log.log_pending_update(
                pending.object_type, pending.object_id,
                pending.changes, pending.expected_current_values,
                pending.user_id, pending.description,
            )

            groups = self._group_changes_by_storage(pending.object_type, pending.changes)
            for adapter, resolved_type_config, group_changes in groups:
                group_expected = {
                    field_name: pending.expected_current_values[field_name]
                    for field_name in group_changes
                }
                success = self._write_fields_with_limiter(
                    pending.object_type, pending.object_id, adapter, resolved_type_config,
                    group_changes, group_expected,
                )
                if not success:
                    # See write_log.py's own docstring for the known,
                    # stated limitation this leaves: if an EARLIER
                    # group already committed successfully before this
                    # one failed, the log entry stays 'pending'
                    # indefinitely, and get_field() will keep reporting
                    # the LATER group's field as updated even though it
                    # never was -- deferred, folded into the same
                    # crash-recovery work rather than solved separately
                    # here.
                    raise ValueError(
                        f"{pending.object_type} {pending.object_id!r} changed since this "
                        f"write was proposed -- refresh and retry"
                    )

            self.write_log.mark_applied(log_id)

        return pending.object_id

    def resume_pending_writes(self) -> dict:
        # Called ONCE, at deployment startup (see api/app.py / scripts/
        # run_deployment.py), before serving any real traffic -- the
        # "resume-on-startup" half of crash recovery write_log.py's own
        # module docstring names as this mechanism's next planned piece
        # of work. Finds every write_log entry still at status='pending'
        # -- each one a write that was logged but never confirmed
        # reaching 'applied', meaning either the process that would have
        # finished it is simply gone (a genuine crash mid-apply), or it
        # hit the ALREADY-KNOWN partial-failure gap (an earlier group
        # committed, a later one didn't, see _apply_update_via_log()'s
        # own comment on this).
        #
        # Reconciles each entry's storage groups against LIVE backend
        # state -- deliberately NOT by blindly re-running write_fields()
        # for every group, which would incorrectly treat an ALREADY-
        # applied group as a fresh failure (its real value no longer
        # matches the OLD expected_current_values the conditional write
        # checks against, precisely BECAUSE it already succeeded). See
        # _resume_one_entry()'s own docstring for how this dispatches
        # between update's three-way classification and create's
        # simpler, two-way one.
        #
        # Naturally idempotent, safe to call more than once -- every
        # judgment is re-derived fresh from live backend state each
        # time; nothing here depends on a "have I already processed
        # this" flag anywhere. Deliberately STARTUP-TIME only, not a
        # continuously-running background process -- see write_log.py's
        # own module docstring for why periodic/continuous resume stays
        # a further, separately-scoped enhancement, not solved here.
        summary = {"resumed": 0, "already_applied": 0, "ambiguous": 0}
        for entry in self.write_log.get_pending_entries():
            object_lock = self.mediator._lock_for_object(entry["object_type"], entry["object_id"])
            with object_lock:
                outcome = self._resume_one_entry(entry)
            summary[outcome] += 1
        return summary

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
        # visible_schema() itself.
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

    def propose_action(self, user_record: UserRecord, action_type_name: str,
                        object_id: Any | None, parameters: dict) -> PendingWrite:
        # Matches Palantir Foundry's own action-type model directly
        # (verified against their docs, not assumed): a NAMED,
        # independently-governed operation, not a generic CRUD verb.
        #
        # RBAC is ACTION-level, deliberately NOT a field-grant hybrid --
        # one "execute:{action_type_name}" grant, not one write:{type}.
        # {field} grant per field the action's mutations happen to
        # touch. A real, considered trade-off, not an oversight: this
        # is CLOSER to Palantir's real model and easier for whoever is
        # actually configuring roles to reason about ("this role may
        # perform this named business operation," not "this role may
        # touch these raw columns") -- but it means a role's true field-
        # level reach is now defined by whatever an action's mutations
        # happen to declare, not by an independent, per-field decision.
        # Editing an action's mutations later is therefore a REAL grant-
        # equivalent decision, not routine schema maintenance -- every
        # role already holding execute: on that action silently gains
        # whatever new mutation was added.
        action_def = self.action_types.get(action_type_name)
        if action_def is None:
            raise ValueError(f"Unknown action_type: {action_type_name!r}")

        object_type = action_def["object_type"]
        operation = action_def["operation"]  # "create" or "update"

        execute_action_id = f"execute:{action_type_name}"
        rbac_allowed = authorize(user_record, self.roles, execute_action_id)
        if not rbac_allowed:
            # Logged ONCE here, with mac_allowed=None -- MAC never ran,
            # short-circuited before a real database query. Never
            # logs twice for the same outcome.
            self.audit_log.log_access(
                user_record.user_id, object_type, object_id, execute_action_id,
                mac_allowed=None, rbac_allowed=False,
            )
            raise PermissionError(f"{user_record.user_id!r} is not authorized for: {execute_action_id!r}")

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

        # Parameter validation -- REQUIRED parameters must be present;
        # UNDECLARED ones are rejected outright, not silently ignored.
        # "Explicit and safe," matching this project's own consistent
        # discipline: never silently accept something unexpected.
        declared_params = action_def.get("parameters", {})
        for param_name, param_spec in declared_params.items():
            if param_spec.get("required") and param_name not in parameters:
                raise ValueError(f"Missing required parameter {param_name!r} for action {action_type_name!r}")
        unknown_params = set(parameters) - set(declared_params)
        if unknown_params:
            raise ValueError(
                f"Unknown parameter(s) for action {action_type_name!r}: {sorted(unknown_params)}"
            )

        # Submission criteria -- structurally a property of the named
        # ACTION, not a generic validation bolted onto whatever
        # "update" happens to mean for an object type (see
        # submission_criteria.py's own docstring). The "parameter"
        # check kind reads from the action's own declared parameter
        # names, a genuinely different namespace than an object's raw
        # field names.
        criteria = action_def.get("submission_criteria", [])
        if criteria:
            current_state = self._read_current_state_for_criteria(object_type, object_id, criteria) \
                if operation == "update" else None
            evaluate_submission_criteria(criteria, current_state, parameters)

        # Resolve the action's DECLARED mutations into a concrete
        # field-value dict -- this, not free-form model input, is what
        # actually gets written. The model chooses WHICH action and
        # supplies typed parameters; it never directly names a raw
        # field to change.
        changes = {
            mutation["set"]["property"]: self._resolve_mutation_value(mutation["set"]["value"], parameters, user_record)
            for mutation in action_def["mutations"]
        }

        # For "create," an explicit id is ALWAYS required now, matching
        # update's own precedent of a SINGLE, unified path regardless
        # of storage count (see confirm_and_execute() below -- update
        # ALWAYS goes through the log, whether it touches one storage
        # or several; create now does too). Not required only because
        # multi-storage needs it structurally -- deliberately unified
        # rather than maintaining two separate mechanisms (a log-based
        # path for multi-storage, a log-free direct path for single-
        # storage), even though a genuinely single-storage create's
        # own INSERT is already atomic on its own and doesn't NEED the
        # log to avoid a half-applied state the way multi-storage does.
        # The real, remaining reason auto-generated ids can't be
        # supported at all now: the log-first-then-apply ordering this
        # whole mechanism depends on needs the id known BEFORE any
        # storage is touched -- an auto-generated id, by definition,
        # isn't known until AFTER an INSERT already ran. Matches
        # Palantir Foundry's own MDO requirement that a primary key
        # already exist, matching, in every backing datasource, not
        # just the multi-storage case specifically.
        #
        # For "update," expected_current_values is built PER STORAGE
        # GROUP (same _group_changes_by_storage() confirm_and_execute()
        # itself uses) -- this is what makes a multi-storage update
        # possible at all; see write_log.py's own module docstring for
        # the full mechanism.
        expected_current_values = {}
        if operation == "update":
            for adapter, resolved_type_config, group_changes in self._group_changes_by_storage(object_type, changes):
                expected_current_values.update(
                    self._read_group_fields(object_type, object_id, adapter, resolved_type_config, group_changes)
                )
        else:
            # _group_changes_by_storage() also validates every field
            # name is real (same as update's own branch above) -- an
            # unknown field in a create's mutations should fail HERE,
            # at proposal time, not later at confirm_and_execute() time
            # after a human may have already approved it.
            self._group_changes_by_storage(object_type, changes)
            id_field = self.mediator._type_schema(object_type)["id_field"]
            if id_field not in changes:
                raise ValueError(
                    f"Create for {object_type!r} requires an explicit {id_field!r} value "
                    f"in its own mutations -- auto-generated ids aren't supported"
                )

        description = f"{action_type_name}({object_id!r}, parameters={parameters})"
        return PendingWrite(object_type, object_id, operation, changes, user_record.user_id,
                             description, expected_current_values)

    def confirm_and_execute(self, pending: PendingWrite, approved: bool) -> dict | None:
        request_id = str(uuid.uuid4())
        self.audit_log.log_pre(
            request_id, pending.user_id, pending.description,
            f"write:{pending.object_type}", pending.changes, approved,
        )

        if not approved:
            return None

        if pending.action == "update":
            # ALWAYS via the write log now -- see write_log.py's own
            # module docstring for the full mechanism. Handles
            # multi-storage updates the old, single-call
            # _resolve_shared_storage() approach genuinely could not
            # (it fails outright the instant it's asked to resolve
            # fields spanning more than one storage).
            new_id = self._apply_update_via_log(pending)
            self.audit_log.log_post(request_id, "success", [new_id])
            return {"status": "written", "object_id": new_id}

        # "create" -- ALWAYS via the write log now too, matching
        # "update"'s own precedent immediately above: one unified
        # mechanism regardless of storage count, not two separately-
        # maintained paths. propose_action() already enforced that the
        # object's own id is present in pending.changes before this was
        # ever proposable -- see its own comment on why this is now
        # required universally, not just when create happens to span
        # multiple storages.
        new_id = self._apply_create_via_log(pending)
        self.audit_log.log_post(request_id, "success", [new_id])
        return {"status": "written", "object_id": new_id}

    def _apply_create_via_log(self, pending: PendingWrite) -> Any:
        # THE create-side counterpart to _apply_update_via_log() -- see
        # write_log.py's own module docstring for the shared mechanism.
        # Handles single-storage create too now, same as
        # _apply_update_via_log() already did for update -- a single-
        # group `groups` list below is simply the degenerate case,
        # nothing here needs to special-case it. Requires pending.changes to
        # already include the type's own id_field, explicitly --
        # propose_action() enforces this upfront; matches Palantir
        # Foundry's own MDO requirement that an object's primary key
        # already exist, matching, in every backing datasource
        # (verified directly, not assumed -- see
        # https://www.palantir.com/docs/foundry/object-permissioning/multi-datasource-objects).
        id_field = self.mediator._type_schema(pending.object_type)["id_field"]
        object_id = pending.changes[id_field]
        # NOT pending.object_id -- see this method's own return
        # statement below for why that's always None for "create."
        # Using it here would be a real bug, not just an unused
        # parameter: it would key the per-object lock identically for
        # EVERY create of this type (needlessly serializing unrelated
        # concurrent creates against each other), and -- more
        # seriously -- store the write_log row itself under the wrong
        # object_id, breaking get_pending_changes()'s own by-id lookup
        # for the real id during the brief window before mark_applied()
        # runs, and breaking resume_pending_writes() outright if a
        # crash happens in that same window.
        object_lock = self.mediator._lock_for_object(pending.object_type, object_id)
        with object_lock:
            log_id = self.write_log.log_pending_create(
                pending.object_type, object_id,
                pending.changes, pending.user_id, pending.description,
            )

            groups = self._group_changes_by_storage(pending.object_type, pending.changes)
            for adapter, resolved_type_config, group_changes in groups:
                # Every group's own row needs the id as one of its
                # actual inserted columns -- unlike update, create_
                # object() has no separate object_id parameter for a
                # WHERE clause; the id is just another field being
                # inserted, into EVERY storage, not just whichever ONE
                # group's mutations happened to place it in naturally
                # (a no-op overwrite for that one group, a real
                # injection for every other).
                group_with_id = {**group_changes, id_field: object_id}
                self._create_object_with_limiter(pending.object_type, adapter, resolved_type_config, group_with_id)

            self.write_log.mark_applied(log_id)

        return object_id
