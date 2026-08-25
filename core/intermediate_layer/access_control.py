"""
access_control.py  (the single canonical enforcement point -- generic, org-agnostic)

check_access() is the ONLY function in the whole project that decides
"is this allowed." Every surface that touches protected data -- reads
(DataMediator), writes (WriteMediator), memory (MemoryGuard) -- calls
THIS, never reimplements the combination itself. This exists
specifically to prevent the most common real cause of permission bugs:
the same logical check implemented in two or three places that quietly
drift out of sync. One choke point cannot drift out of sync with itself.

TWO gates, both required, matching Palantir's own Markings (MAC) +
role (RBAC) pattern:
  1. MAC -- DataMediator._security_allowed(): the mandatory,
     non-negotiable region/org boundary. Re-derived live on every call,
     never trusted from a stored label (see core/memory/guard.py's
     docstring for why).
  2. RBAC -- auth.authorize(): does this user's ROLE include this
     specific action? Roles are defined in policy.yaml, not hardcoded.

LOGS EVERY DECISION, allow or deny, with the MAC/RBAC breakdown visible
independently -- not just the final yes/no. A denied read is often more
security-valuable to have on record than an allowed one, since it's how
a misconfigured role gets caught before it becomes an incident.

Used by: core/ontology/mediator.py (every read), core/ontology/
         write_mediator.py (every write proposal), core/memory/guard.py
         (every memory read)
"""

from core.intermediate_layer.audit import log_access
from core.intermediate_layer.auth import authorize, get_user_security_value


def check_access(mediator, users: dict, roles: dict, security_attribute: str,
                  user_id: str, object_type: str, object_id, action: str) -> bool:
    user_security_value = get_user_security_value(users, user_id, security_attribute)
    mac_allowed = (
        user_security_value is not None
        and mediator._security_allowed(object_type, object_id, user_security_value)
    )
    rbac_allowed = authorize(users, roles, user_id, action)

    log_access(user_id, object_type, object_id, action, mac_allowed, rbac_allowed)

    return mac_allowed and rbac_allowed
