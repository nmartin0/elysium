"""
access_control.py  (the single canonical enforcement point -- generic, org-agnostic)

check_access() is the ONLY function in the whole project that decides
"is this allowed." Every surface that touches protected data --
DataMediator's reads, WriteMediator's writes, MemoryGuard's memory
reads -- calls THIS, never reimplements the combination itself.

Takes a pre-resolved UserRecord, not a raw user_id + users dict --
resolution happens ONCE per request (see core/intermediate_layer/
auth.py's resolve_user_record()), not on every single call here. This
also means check_access() itself no longer needs users/
security_attribute at all -- UserRecord already carries the resolved
MAC value, a real reduction in what this function needs to know, not
just a relocation of the same parameters.

TWO gates, both required, matching Palantir's own Markings (MAC) +
role (RBAC) pattern:
  1. MAC -- DataMediator._security_allowed(), using user_record.
     security_value. Re-derived live from the OBJECT's own data on
     every call, never trusted from anywhere else.
  2. RBAC -- auth.authorize(), using user_record.role_name.

LOGS EVERY DECISION, allow or deny, with the MAC/RBAC breakdown visible
independently.

Used by: core/ontology/mediator.py (every read), core/ontology/
         write_mediator.py (every write proposal), core/memory/guard.py
         (every memory read)
"""

from core.intermediate_layer.audit import log_access
from core.intermediate_layer.auth import authorize, UserRecord


def check_access(mediator, user_record: UserRecord, roles: dict,
                  object_type: str, object_id, action: str) -> bool:
    mac_allowed = (
        user_record.security_value is not None
        and mediator._security_allowed(object_type, object_id, user_record.security_value)
    )
    rbac_allowed = authorize(user_record, roles, action)

    log_access(user_record.user_id, object_type, object_id, action, mac_allowed, rbac_allowed)

    return mac_allowed and rbac_allowed
