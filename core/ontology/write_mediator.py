"""
write_mediator.py  (the write path -- generic, org-agnostic)

Takes a pre-resolved UserRecord, not a raw user_id -- same reduction as
DataMediator: WriteMediator no longer holds users/security_attribute at
all, only roles (still shared, static config, unaffected by this
change).

Two stages: propose_write() checks RBAC+MAC and snapshots the fields
about to change; confirm_and_execute() re-verifies that snapshot
ATOMICALLY at write time (per-object lock + adapter.write_fields()'s
conditional SQL), preventing lost updates. PendingWrite is frozen --
nothing about a proposed write can change between human approval and
execution.

RBAC is field-level, matching reads: EVERY field in `changes` needs its
own explicit write:{object_type}.{field_name} grant -- there is no
blanket write:{object_type} action. A create additionally needs
create:{object_type}. ALL required actions for one proposed write are
evaluated together (not short-circuited on the first failure) and each
logged individually via audit.log_access(). Only after every required
action passes does MAC get checked (updates only -- no existing object
to check a region boundary on for a create).

TWO SEPARATE PROPOSAL PATHS, DELIBERATELY, on the action-types-redesign
branch: propose_write() (free-form field grants, above) is the ORIGINAL
path, untouched here -- and propose_action() (execute: grants, declared
mutations, below) is genuinely NEW, matching Palantir Foundry's own
action-type model verified directly against their docs. These are NOT
meant to coexist long-term -- see propose_action()'s own docstring for
why a hybrid/dual-path design was considered and rejected. This file
holds both ONLY during this branch's build-and-prove-in-isolation
phase; a later, separate migration pass replaces every propose_write()
call site with propose_action() and removes propose_write() entirely.
submission_criteria (see core/ontology/submission_criteria.py)
belongs EXCLUSIVELY to propose_action() for this same reason -- it is
structurally a property of a named ACTION in Palantir's own model, not
a generic validation bolted onto whatever "update" happens to mean for
an object type.

Used by: core/agent/agentic_loop.py's AgentLoop (write_mediator +
         confirm_write callback, both None if writes are disabled)
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from core.intermediate_layer.audit import log_access, log_pre, log_post
from core.intermediate_layer.auth import authorize, UserRecord
from core.ontology.mediator import DataMediator
from core.ontology.schema import get_field_column
from core.ontology.submission_criteria import evaluate_submission_criteria


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
    def __init__(self, mediator: DataMediator, roles: dict, action_types: dict | None = None):
        self.mediator = mediator
        self.roles = roles
        # NEW, separate from `mediator` deliberately -- action types are
        # a WRITE-path concept (governed mutations), and DataMediator is
        # scoped specifically to reads/routing (see its own docstring).
        # Optional, defaulting to {} -- every existing caller that never
        # constructs a WriteMediator with named actions in mind keeps
        # working completely unchanged.
        self.action_types = action_types or {}

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

    def _describe(self, object_type: str, object_id: Any | None, action: str, changes: dict) -> str:
        if action == "create":
            return f"Create a new {object_type} with: {changes}"
        return f"Update {object_type} {object_id!r}: set {changes}"

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
        type_schema = self.mediator._type_schema(object_type)
        needed_fields = {c["field"] for c in criteria if c["check"] == "current_state"}
        current_state = {}
        for field_name in needed_fields:
            adapter, resolved_type_config = self.mediator._resolve_shared_storage(object_type, [field_name])
            column = get_field_column(type_schema["fields"][field_name], field_name)
            current_state[field_name] = adapter.get_raw_field(object_type, object_id, column, resolved_type_config)
        return current_state

    def propose_write(self, user_record: UserRecord, object_type: str, object_id: Any | None,
                       action: str, changes: dict) -> PendingWrite:
        # Every action this write needs, field-level -- create: once,
        # plus one write:{type}.{field} per field being set.
        action_ids = []
        if action == "create":
            action_ids.append(f"create:{object_type}")
        action_ids.extend(f"write:{object_type}.{field_name}" for field_name in changes)

        rbac_results = {aid: authorize(user_record, self.roles, aid) for aid in action_ids}
        rbac_allowed = all(rbac_results.values())

        if not rbac_allowed:
            # Logged individually -- an auditor can see EXACTLY which
            # grant(s) were missing, not just "denied." Short-circuits
            # BEFORE MAC (mac_allowed=None, not evaluated) -- a request
            # that's already going to be denied shouldn't trigger a
            # real database query.
            for aid, allowed in rbac_results.items():
                log_access(user_record.user_id, object_type, object_id, aid, mac_allowed=None, rbac_allowed=allowed)
            denied = [aid for aid, allowed in rbac_results.items() if not allowed]
            raise PermissionError(f"{user_record.user_id!r} is not authorized for: {denied}")

        if action == "create":
            # No existing object to check a region boundary on -- see
            # module docstring for why mac_allowed=True here means "not
            # applicable," not "a check ran and passed."
            mac_allowed = True
        else:
            mac_allowed = (
                user_record.security_value is not None
                and self.mediator._security_allowed(object_type, object_id, user_record.security_value)
            )

        for aid in action_ids:
            log_access(user_record.user_id, object_type, object_id, aid, mac_allowed, rbac_results[aid])

        if not mac_allowed:
            raise PermissionError(f"{user_record.user_id!r} cannot modify this {object_type}")

        # MDO: every field in `changes` must share ONE storage -- the
        # same v1 scope boundary as reads (see DataMediator.
        # _resolve_shared_storage()'s own docstring). This runs for
        # BOTH create and update -- a create populating fields from
        # multiple storages would need multiple separate insert
        # statements, one per silo, which is real, unsolved multi-
        # storage-write territory intentionally out of scope for v1,
        # not just an update-specific concern.
        adapter, resolved_type_config = self.mediator._resolve_shared_storage(object_type, list(changes.keys()))

        # Snapshot for lost-update detection -- captured here, verified
        # atomically at execute time. Direct adapter read, not
        # mediator.get_field() -- access was already confirmed above.
        # Reads via each field's REAL column name (itself, unless MDO
        # overrides it -- see get_field_column()'s docstring), but
        # stays keyed by field_name throughout PendingWrite -- field
        # names are the human/model-facing vocabulary; translation to
        # raw SQL column names happens once, right before the adapter
        # call, in confirm_and_execute() below.
        expected_current_values = {}
        if action == "update":
            expected_current_values = {
                field_name: adapter.get_raw_field(
                    object_type, object_id,
                    get_field_column(resolved_type_config["fields"][field_name], field_name),
                    resolved_type_config,
                )
                for field_name in changes
            }

        description = self._describe(object_type, object_id, action, changes)
        return PendingWrite(object_type, object_id, action, dict(changes), user_record.user_id,
                             description, expected_current_values)

    def _resolve_mutation_value(self, value_spec, parameters: dict):
        # A mutation's "value" is either a LITERAL (used as-is) or a
        # reference to one of the action's own declared parameters,
        # written "parameter.<name>" -- resolved here, once, at
        # proposal time. Deliberately a plain string-prefix convention,
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
        return value_spec

    def propose_action(self, user_record: UserRecord, action_type_name: str,
                        object_id: Any | None, parameters: dict) -> PendingWrite:
        # The NEW proposal path -- matches Palantir Foundry's own
        # action-type model directly (verified against their docs, not
        # assumed): a NAMED, independently-governed operation, not a
        # generic CRUD verb. See this module's own docstring for why
        # this exists alongside (temporarily) propose_write(), and why
        # submission_criteria belongs here specifically.
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
            # short-circuited before a real database query. Matches
            # propose_write()'s own pattern exactly: never log twice
            # for the same outcome.
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

        # Submission criteria -- reuses evaluate_submission_criteria()
        # UNCHANGED, fed `parameters` where propose_write() would feed
        # `changes`. The "parameter" check kind (vs "proposed_value")
        # is what makes this correct: it reads from the action's own
        # declared parameter names, a genuinely different namespace
        # than an object's raw field names -- see submission_criteria.py's
        # own docstring for the full reasoning.
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
            mutation["set"]["property"]: self._resolve_mutation_value(mutation["set"]["value"], parameters)
            for mutation in action_def["mutations"]
        }

        # From here, IDENTICAL to propose_write()'s own tail -- MDO
        # storage resolution, expected_current_values snapshot,
        # returning the SAME PendingWrite shape confirm_and_execute()
        # already knows how to execute, completely unchanged.
        adapter, resolved_type_config = self.mediator._resolve_shared_storage(object_type, list(changes.keys()))
        expected_current_values = {}
        if operation == "update":
            expected_current_values = {
                field_name: adapter.get_raw_field(
                    object_type, object_id,
                    get_field_column(resolved_type_config["fields"][field_name], field_name),
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

        adapter, resolved_type_config = self.mediator._resolve_shared_storage(
            pending.object_type, list(pending.changes.keys())
        )
        write_limiter = self.mediator._write_limiter_for(pending.object_type)

        # Translates field names to their real SQL column names, once,
        # right here -- the only place PendingWrite's field-name-keyed
        # dicts actually reach the adapter/SQL layer. Every field in
        # ONE write already shares one storage/type_config by this
        # point (validated in propose_write()), so a single resolved
        # type_config correctly covers every field being translated.
        def _to_columns(values_by_field: dict) -> dict:
            return {
                get_field_column(resolved_type_config["fields"][field_name], field_name): value
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
