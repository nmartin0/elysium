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
from pathlib import Path
from typing import Any, Literal

from core.intermediate_layer.audit import log_access, log_pre, log_post
from core.intermediate_layer.auth import authorize, UserRecord
from core.ontology import write_log
from core.ontology.mediator import DataMediator
from core.ontology.schema import get_column_for_field
from core.ontology.submission_criteria import evaluate_submission_criteria


def _fields_to_columns(resolved_type_config: dict, values_by_field: dict) -> dict:
    # Standalone, not a method -- needs no WriteMediator state, and is
    # called once per storage GROUP now (see _group_changes_by_storage()),
    # each with its own resolved_type_config, rather than once per call
    # with a single, closure-captured one the way confirm_and_execute()'s
    # own inline _to_columns() below still does for its unchanged,
    # single-storage direct-write path.
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
    def __init__(self, mediator: DataMediator, roles: dict, action_types: dict | None = None,
                 write_log_db_path: Path | None = None):
        self.mediator = mediator
        self.roles = roles
        # Optional, defaulting to {} -- a deployment with no action
        # types declared at all (writes fully disabled, or none
        # authored yet) is still a valid, legitimate state: propose_action()
        # simply raises "Unknown action_type" for any name, and
        # visible_action_types() returns {} for every user, same as
        # never offering write capability at all.
        self.action_types = action_types or {}
        # Optional, defaulting to None -- see write_log.py's own module
        # docstring for the full mechanism this enables. None means
        # confirm_and_execute() below falls back to the ORIGINAL,
        # direct-write path unchanged (still the only path for
        # "create," and still what every existing caller/test gets
        # without any change to their own behavior). This mirrors this
        # project's own already-proven transition shape for
        # propose_write() -> propose_action(): build the new mechanism
        # as an opt-in addition, prove it in isolation, migrate every
        # real caller, THEN remove the fallback and this parameter's
        # optionality entirely -- not a permanent second path.
        self.write_log_db_path = write_log_db_path

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
        write_limiter = self.mediator._write_limiter_for(pending.object_type)
        with object_lock:
            log_id = write_log.log_pending_write(
                self.write_log_db_path, pending.object_type, pending.object_id,
                pending.changes, pending.expected_current_values,
                pending.user_id, pending.description,
            )

            groups = self._group_changes_by_storage(pending.object_type, pending.changes)
            for adapter, resolved_type_config, group_changes in groups:
                group_expected = {
                    field_name: pending.expected_current_values[field_name]
                    for field_name in group_changes
                }
                with write_limiter.limit():
                    success = adapter.write_fields(
                        pending.object_type, pending.object_id,
                        _fields_to_columns(resolved_type_config, group_changes),
                        _fields_to_columns(resolved_type_config, group_expected),
                        resolved_type_config,
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

            write_log.mark_applied(self.write_log_db_path, log_id)

        return pending.object_id

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
        # Direct adapter reads, not mediator.get_field() -- same
        # reasoning as expected_current_values below: this is a
        # mechanical, internal check the system makes on its own
        # authority, not something gated by the acting user's own
        # field-level read grants.
        needed_fields = {c["field"] for c in criteria if c["check"] == "current_state"}
        current_state = {}
        for field_name in needed_fields:
            adapter, resolved_type_config = self.mediator._resolve_shared_storage(object_type, [field_name])
            column = get_column_for_field(resolved_type_config, field_name)
            current_state[field_name] = adapter.get_raw_field(object_type, object_id, column, resolved_type_config)
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
            log_access(
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
        log_access(user_record.user_id, object_type, object_id, execute_action_id, mac_allowed, rbac_allowed)
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

        # MDO: every field in `changes` must share ONE storage, UNLESS
        # write_log_db_path is configured -- see write_log.py's own
        # module docstring for the full mechanism. When it's set,
        # expected_current_values is built PER STORAGE GROUP (same
        # _group_changes_by_storage() confirm_and_execute() itself
        # uses), so this never hits the single, whole-dict resolution
        # call's outright rejection. When it's None (the original,
        # still-valid fallback), this keeps the EXACT original
        # behavior -- one call, one storage, reject anything spanning
        # more than one -- see DataMediator._resolve_shared_storage()'s
        # own docstring for that v1 scope boundary.
        expected_current_values = {}
        if operation == "update" and self.write_log_db_path is not None:
            for adapter, resolved_type_config, group_changes in self._group_changes_by_storage(object_type, changes):
                for field_name in group_changes:
                    expected_current_values[field_name] = adapter.get_raw_field(
                        object_type, object_id,
                        get_column_for_field(resolved_type_config, field_name),
                        resolved_type_config,
                    )
        else:
            adapter, resolved_type_config = self.mediator._resolve_shared_storage(object_type, list(changes.keys()))
            if operation == "update":
                expected_current_values = {
                    field_name: adapter.get_raw_field(
                        object_type, object_id,
                        get_column_for_field(resolved_type_config, field_name),
                        resolved_type_config,
                    )
                    for field_name in changes
                }

        description = f"{action_type_name}({object_id!r}, parameters={parameters})"
        return PendingWrite(object_type, object_id, operation, changes, user_record.user_id,
                             description, expected_current_values)

    def confirm_and_execute(self, pending: PendingWrite, approved: bool) -> dict | None:
        request_id = str(uuid.uuid4())
        log_pre(
            request_id, pending.user_id, pending.description,
            f"write:{pending.object_type}", pending.changes, approved,
        )

        if not approved:
            return None

        if pending.action == "update" and self.write_log_db_path is not None:
            # THE new write-log path -- see write_log.py's own module
            # docstring for the full mechanism and its current,
            # deliberate scope boundary. Handles multi-storage updates
            # the direct-write path below genuinely cannot: it fails
            # outright the instant _resolve_shared_storage() is asked
            # to resolve fields spanning more than one storage in a
            # single call, exactly what happens two lines below it.
            new_id = self._apply_update_via_log(pending)
            log_post(request_id, "success", [new_id])
            return {"status": "written", "object_id": new_id}

        # ORIGINAL, direct-write path -- UNCHANGED. Still the only path
        # for "create" (see write_log.py's own docstring for why
        # multi-storage create is a separate, harder, not-yet-solved
        # problem), and still the fallback for "update" whenever no
        # write_log_db_path was configured -- see this class's own
        # __init__ for why that remains a valid, TEMPORARY, transitional
        # state right now, not a permanent second path.
        adapter, resolved_type_config = self.mediator._resolve_shared_storage(
            pending.object_type, list(pending.changes.keys())
        )
        write_limiter = self.mediator._write_limiter_for(pending.object_type)

        # Translates field names to their real SQL column names, once,
        # right here -- the only place PendingWrite's field-name-keyed
        # dicts actually reach the adapter/SQL layer. Every field in
        # ONE write already shares one storage/type_config by this
        # point (validated in propose_action()), so a single resolved
        # type_config correctly covers every field being translated.
        def _to_columns(values_by_field: dict) -> dict:
            return {
                get_column_for_field(resolved_type_config, field_name): value
                for field_name, value in values_by_field.items()
            }

        if pending.action == "update":
            # Per-object lock: the PRIMARY correctness mechanism -- two
            # writers to the SAME object serialize here; different
            # objects proceed fully concurrently.
            object_lock = self.mediator._lock_for_object(pending.object_type, pending.object_id)
            with object_lock, write_limiter.limit():
                success = adapter.write_fields(
                    pending.object_type, pending.object_id, _to_columns(pending.changes),
                    _to_columns(pending.expected_current_values), resolved_type_config,
                )
            if not success:
                raise ValueError(
                    f"{pending.object_type} {pending.object_id!r} changed since this "
                    f"write was proposed -- refresh and retry"
                )
            new_id = pending.object_id
        else:
            with write_limiter.limit():
                new_id = adapter.create_object(pending.object_type, _to_columns(pending.changes), resolved_type_config)

        log_post(request_id, "success", [new_id])
        return {"status": "written", "object_id": new_id}
