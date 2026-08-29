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
    def __init__(self, mediator: DataMediator, roles: dict, action_types: dict,
                 write_log_db_path: Path):
        # action_types and write_log_db_path are BOTH required, not
        # optional -- a WriteMediator's only real capability is
        # propose_action(), which is useless without declared actions,
        # and confirm_and_execute() now depends entirely on the write
        # log for "update" (see below). Both used to default to a
        # None-shaped fallback during this mechanism's OWN
        # build-and-prove-in-isolation phase, mirroring this project's
        # already-proven propose_write()->propose_action() transition
        # shape -- but verified directly, EVERY real construction site
        # already passed both explicitly; nothing depended on the
        # defaults. Keeping optionality alive after migration is
        # actually complete is compat cruft, not a real capability --
        # removed rather than left as unused, confusing dead weight.
        self.mediator = mediator
        self.roles = roles
        self.action_types = action_types
        self.write_log_db_path = write_log_db_path
        # Catches a REAL, easy-to-make configuration mistake outright,
        # at construction time, rather than letting it fail silently
        # and dangerously later: writes would go through the log
        # correctly, but reads (DataMediator.get_field()) would never
        # check it, since it's checking ITS OWN write_log_db_path, not
        # this one. Both must point at the SAME physical file.
        # Deliberately a real, explicit check (not assert) -- assert
        # statements are stripped entirely under python -O, and this
        # guards a genuine, dangerous-if-silent misconfiguration, not
        # a debugging aid.
        if mediator.write_log_db_path != write_log_db_path:
            raise ValueError(
                f"WriteMediator's write_log_db_path ({write_log_db_path!r}) must match "
                f"the DataMediator it wraps ({mediator.write_log_db_path!r}) -- otherwise "
                f"writes go through the log but reads never check it."
            )

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
                # THE limiter for THIS group's own silo -- a real bug,
                # caught by directly tracing this exact call chain, not
                # just reasoned about: this used to be resolved ONCE,
                # outside this loop, from pending.object_type alone,
                # which ALWAYS resolves to the PRIMARY silo (see
                # DataMediator._write_limiter_for()). A group writing
                # to a DIFFERENT storage (any MDO additional_storage)
                # would silently borrow the PRIMARY silo's concurrency
                # limiter instead of its own -- wrong capacity
                # accounting in both directions: under-protecting the
                # real target silo if it has a stricter limit, and
                # needlessly contending for the primary silo's slots
                # for a write that never touches it at all.
                write_limiter = self.mediator._write_limiter_for_silo(resolved_type_config["storage"]["silo"])
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

        # For "create," every field must still share ONE storage --
        # multi-storage create is a genuinely separate, harder problem
        # (identity propagation: which storage's row gets the
        # canonical id, and how does every OTHER storage's row learn
        # it) not yet solved -- see write_log.py's own module
        # docstring. This call is the outright rejection guard for
        # that case; nothing else in this branch needs its result,
        # since a create has no existing values to snapshot at all.
        #
        # For "update," expected_current_values is built PER STORAGE
        # GROUP (same _group_changes_by_storage() confirm_and_execute()
        # itself uses) -- this is what makes a multi-storage update
        # possible at all; see write_log.py's own module docstring for
        # the full mechanism.
        expected_current_values = {}
        if operation == "update":
            for adapter, resolved_type_config, group_changes in self._group_changes_by_storage(object_type, changes):
                for field_name in group_changes:
                    expected_current_values[field_name] = adapter.get_raw_field(
                        object_type, object_id,
                        get_column_for_field(resolved_type_config, field_name),
                        resolved_type_config,
                    )
        else:
            self.mediator._resolve_shared_storage(object_type, list(changes.keys()))

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

        if pending.action == "update":
            # ALWAYS via the write log now -- see write_log.py's own
            # module docstring for the full mechanism. Handles
            # multi-storage updates the old, single-call
            # _resolve_shared_storage() approach genuinely could not
            # (it fails outright the instant it's asked to resolve
            # fields spanning more than one storage).
            new_id = self._apply_update_via_log(pending)
            log_post(request_id, "success", [new_id])
            return {"status": "written", "object_id": new_id}

        # "create" -- still single-storage only. Multi-storage create
        # is a genuinely separate, harder problem (identity
        # propagation: which storage's row gets the canonical id, and
        # how does every OTHER storage's row learn it) not yet solved
        # -- see write_log.py's own module docstring. No per-object
        # lock needed here (unlike "update" above) -- there's no
        # existing object to race against yet; only the database's own
        # native INSERT atomicity matters.
        adapter, resolved_type_config = self.mediator._resolve_shared_storage(
            pending.object_type, list(pending.changes.keys())
        )
        write_limiter = self.mediator._write_limiter_for(pending.object_type)

        def _to_columns(values_by_field: dict) -> dict:
            return {
                get_column_for_field(resolved_type_config, field_name): value
                for field_name, value in values_by_field.items()
            }

        with write_limiter.limit():
            new_id = adapter.create_object(pending.object_type, _to_columns(pending.changes), resolved_type_config)

        log_post(request_id, "success", [new_id])
        return {"status": "written", "object_id": new_id}
