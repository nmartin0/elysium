"""
write_mediator.py  (the write path -- generic, org-agnostic)

Every write goes through TWO stages, never one: propose_write() decides
whether the write is even allowed to be PROPOSED (two separate checks --
see below), then confirm_and_execute() runs only after a human has
approved the EXACT PendingWrite the check produced. PendingWrite is
frozen -- once built, its contents literally cannot change (a
FrozenInstanceError, not just a convention), so there is no code path
between "human sees this" and "this executes" where the LLM could alter
what gets written.

TWO CHECKS in propose_write(), genuinely different questions:
  1. auth.authorize() -- is this user allowed to write to this object
     TYPE at all? This is the first real activation of policy.yaml's
     allowed_actions, unused everywhere else in the project so far.
     Convention: action_id = f"write:{object_type}".
  2. DataMediator._security_allowed() -- for an UPDATE specifically, is
     THIS particular object within the user's row-level access scope?
     Same check every read already uses.
A user failing check 1 never reaches check 2 -- and per the design
conversation, that's deliberate: a flatly-disallowed user should never
see a "here's what would happen" confirmation surface at all, since
that would leak the existence of a capability they don't have.

AUDITED UNCONDITIONALLY, before execution -- log_pre() records the
proposal and the human's decision even if the write is rejected;
log_post() only fires if it actually ran. Reuses core/intermediate_layer/
audit.py's real log_pre()/log_post() functions directly, not a
parallel logging mechanism.

Used by: core/agent/agentic_loop.py's AgentLoop (via a write_mediator +
         confirm_write callback, both None if a deployment has no
         write capability enabled)
"""

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from core.intermediate_layer.audit import log_pre, log_post
from core.intermediate_layer.auth import authorize, get_user_security_value
from core.ontology.mediator import DataMediator


@dataclass(frozen=True)
class PendingWrite:
    # Immutable once created -- nothing about a proposed write can be
    # edited after the fact, only approved or rejected as a whole.
    object_type: str
    object_id: Any | None       # None for creates
    action: Literal["update", "create"]
    changes: dict
    user_id: str
    description: str             # deterministic, built by core/ -- never LLM output


class WriteMediator:
    def __init__(self, mediator: DataMediator, users: dict, security_attribute: str):
        self.mediator = mediator
        self.users = users
        self.security_attribute = security_attribute

    def _describe(self, object_type: str, object_id: Any | None, action: str, changes: dict) -> str:
        if action == "create":
            return f"Create a new {object_type} with: {changes}"
        return f"Update {object_type} {object_id!r}: set {changes}"

    def propose_write(self, user_id: str, object_type: str, object_id: Any | None,
                       action: str, changes: dict) -> PendingWrite:
        action_id = f"write:{object_type}"
        if not authorize(self.users, user_id, action_id):
            raise PermissionError(f"{user_id!r} is not authorized for {action_id!r}")

        if action == "update":
            user_security_value = get_user_security_value(self.users, user_id, self.security_attribute)
            if not self.mediator._security_allowed(object_type, object_id, user_security_value):
                raise PermissionError(f"{user_id!r} cannot modify this {object_type}")

        description = self._describe(object_type, object_id, action, changes)
        return PendingWrite(object_type, object_id, action, dict(changes), user_id, description)

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

        if pending.action == "update":
            for field_name, value in pending.changes.items():
                adapter.write_field(pending.object_type, pending.object_id, field_name, value, type_config)
            new_id = pending.object_id
        else:
            new_id = adapter.create_object(pending.object_type, pending.changes, type_config)

        log_post(request_id, "success", [new_id])
        return {"status": "written", "object_id": new_id}
