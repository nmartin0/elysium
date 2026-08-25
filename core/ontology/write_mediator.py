"""
write_mediator.py  (the write path -- generic, org-agnostic)

Two stages: propose_write() checks RBAC+MAC and snapshots the fields
about to change; confirm_and_execute() re-verifies that snapshot
ATOMICALLY at write time (per-object lock + adapter.write_fields()'s
conditional SQL), preventing lost updates -- see core/ontology/
mediator.py's docstring for why a semaphore alone can't do this.
PendingWrite is frozen -- nothing about a proposed write can change
between human approval and execution.

Called: authorize() then (for updates) _security_allowed() -- RBAC
short-circuits before MAC, both logged via audit.log_access(). Writes
are also logged via log_pre()/log_post() -- the attempt and its outcome,
a different question from the MAC/RBAC breakdown.

Used by: core/agent/agentic_loop.py's AgentLoop (write_mediator +
         confirm_write callback, both None if writes are disabled)
"""

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from core.intermediate_layer.audit import log_access, log_pre, log_post
from core.intermediate_layer.auth import authorize, get_user_security_value
from core.ontology.mediator import DataMediator


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
    def __init__(self, mediator: DataMediator, users: dict, roles: dict, security_attribute: str):
        self.mediator = mediator
        self.users = users
        self.roles = roles
        self.security_attribute = security_attribute

    def _describe(self, object_type: str, object_id: Any | None, action: str, changes: dict) -> str:
        if action == "create":
            return f"Create a new {object_type} with: {changes}"
        return f"Update {object_type} {object_id!r}: set {changes}"

    def propose_write(self, user_id: str, object_type: str, object_id: Any | None,
                       action: str, changes: dict) -> PendingWrite:
        action_id = f"write:{object_type}"
        rbac_allowed = authorize(self.users, self.roles, user_id, action_id)

        if not rbac_allowed:
            # Short-circuit BEFORE the MAC check -- both for the
            # "don't leak capability existence" reason from the design
            # conversation, and because computing MAC here would mean a
            # real database query (and, for a malformed/None object_id
            # on a create, a possible confusing crash) for a user who
            # was never going to be allowed regardless of the result.
            log_access(user_id, object_type, object_id, action_id, mac_allowed=None, rbac_allowed=False)
            raise PermissionError(f"{user_id!r} is not authorized for {action_id!r}")

        if action == "create":
            # No existing object to check a region boundary on -- see
            # module docstring for why mac_allowed=True here means "not
            # applicable," not "a check ran and passed."
            mac_allowed = True
        else:
            user_security_value = get_user_security_value(self.users, user_id, self.security_attribute)
            mac_allowed = (
                user_security_value is not None
                and self.mediator._security_allowed(object_type, object_id, user_security_value)
            )

        log_access(user_id, object_type, object_id, action_id, mac_allowed, rbac_allowed)

        if not mac_allowed:
            raise PermissionError(f"{user_id!r} cannot modify this {object_type}")

        # Snapshot for lost-update detection -- captured here, verified
        # atomically at execute time. Direct adapter read, not
        # mediator.get_field() -- access was already confirmed above;
        # re-running check_access() here would blur "did data change"
        # with "is this still allowed," different questions.
        expected_current_values = {}
        if action == "update":
            adapter = self.mediator._adapter_for(object_type)
            type_config = self.mediator._type_schema(object_type)
            expected_current_values = {
                field_name: adapter.get_raw_field(object_type, object_id, field_name, type_config)
                for field_name in changes
            }

        description = self._describe(object_type, object_id, action, changes)
        return PendingWrite(object_type, object_id, action, dict(changes), user_id,
                             description, expected_current_values)

    def confirm_and_execute(self, pending: PendingWrite, approved: bool) -> dict | None:
        request_id = str(uuid.uuid4())
        log_pre(
            request_id, pending.user_id, pending.description,
            f"write:{pending.object_type}", pending.changes, approved,
        )

        if not approved:
            return None

        adapter = self.mediator._adapter_for(pending.object_type)
        type_config = self.mediator._type_schema(pending.object_type)
        write_limiter = self.mediator._write_limiter_for(pending.object_type)

        if pending.action == "update":
            # Per-object lock: the PRIMARY correctness mechanism -- two
            # writers to the SAME object serialize here; different
            # objects proceed fully concurrently. Write semaphore:
            # adapter's own declared capacity exception (e.g. SQLite's
            # whole-file lock), narrower and separate from correctness.
            object_lock = self.mediator._lock_for_object(pending.object_type, pending.object_id)
            with object_lock, write_limiter.limit():
                success = adapter.write_fields(
                    pending.object_type, pending.object_id, pending.changes,
                    pending.expected_current_values, type_config,
                )
            if not success:
                raise ValueError(
                    f"{pending.object_type} {pending.object_id!r} changed since this "
                    f"write was proposed -- refresh and retry"
                )
            new_id = pending.object_id
        else:
            with write_limiter.limit():
                new_id = adapter.create_object(pending.object_type, pending.changes, type_config)

        log_post(request_id, "success", [new_id])
        return {"status": "written", "object_id": new_id}
