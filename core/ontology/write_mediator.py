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
    def __init__(self, mediator: DataMediator, roles: dict):
        self.mediator = mediator
        self.roles = roles

    def _describe(self, object_type: str, object_id: Any | None, action: str, changes: dict) -> str:
        if action == "create":
            return f"Create a new {object_type} with: {changes}"
        return f"Update {object_type} {object_id!r}: set {changes}"

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
