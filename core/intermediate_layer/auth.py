"""
auth.py  (identity resolution + RBAC -- generic mechanism, no org data)

UserRecord is an immutable snapshot of one user's identity, resolved
ONCE per request (resolve_user_record()), threaded explicitly through
everything downstream (DataMediator, WriteMediator, MemoryGuard,
AgentLoop) instead of a raw user_id string re-looked-up on every check.

This replaced an earlier design (a dict-like object whose .get()
queried live on every call) that looked cheap but wasn't: a real
database lookup disguised as a free dict access, paid ONCE PER OBJECT
TOUCHED rather than once per request, and vulnerable to a role changing
mid-request and different checks within the same traversal seeing
different answers. Resolving once, up front, and using that one
immutable snapshot for the whole request closes both problems -- same
principle AgentLoop.run() already uses for visible_schema().

resolve_user_record() ALWAYS returns a record, even for an unknown
user_id -- both fields None. An unknown user fails every downstream
check through the exact SAME path as a known-but-unprivileged one,
rather than a special early-exit case scattered across callers.

authorize() is RBAC -- role-based, not per-user. A user with no role,
or a role not present in `roles`, is denied by default. RBAC and MAC
are DELIBERATELY separate checks, never merged into one function here
-- core/intermediate_layer/access_control.py's check_access() is the
one place that combines both.

Called by: core/intermediate_layer/access_control.py,
           core/ontology/mediator.py, core/ontology/write_mediator.py,
           core/agent/agentic_loop.py
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UserRecord:
    user_id: str
    security_value: str | None    # MAC value, e.g. this user's region -- None if unknown/unset
    role_name: str | None          # RBAC role -- None if unknown/unassigned


def resolve_user_record(users: dict, user_id: str, security_attribute: str) -> UserRecord:
    user = users.get(user_id, {})
    return UserRecord(user_id, user.get(security_attribute), user.get("role"))


def authorize(user_record: UserRecord, roles: dict, action_id: str) -> bool:
    if user_record.role_name is None:
        return False
    role = roles.get(user_record.role_name)
    if role is None:
        return False
    return action_id in role.get("allowed_actions", frozenset())
