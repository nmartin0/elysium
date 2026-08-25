"""
auth.py  (the RBAC layer -- generic mechanism, no org data)

Three functions:
  - get_user_role(): which named role does this user have?
  - authorize(): does that role's allowed_actions include this specific
    action? This is RBAC -- role-based, not per-user. A user with no
    role, or a role not present in `roles`, is denied by default.
  - get_user_security_value(): unchanged from before -- the row-level
    (MAC-style) access value, for whatever attribute policy.yaml's
    security_attribute names.

This file only knows the SHAPE user/role data must have, never its
actual contents -- that's deployment/policy.yaml's job.

RBAC and MAC are DELIBERATELY separate checks, never merged into one
function here -- core/intermediate_layer/access_control.py's
check_access() is the one place that combines both, so there is exactly
one canonical enforcement point rather than each caller reimplementing
"both must pass" slightly differently.

Called by: core/intermediate_layer/access_control.py,
           core/ontology/write_mediator.py
"""


def get_user_role(users: dict, user_id: str) -> str | None:
    user = users.get(user_id)
    if user is None:
        return None
    return user.get("role")


def authorize(users: dict, roles: dict, user_id: str, action_id: str) -> bool:
    role_name = get_user_role(users, user_id)
    if role_name is None:
        return False
    role = roles.get(role_name)
    if role is None:
        return False
    return action_id in role.get("allowed_actions", [])


def get_user_security_value(users: dict, user_id: str, security_attribute: str) -> str | None:
    user = users.get(user_id)
    if user is None:
        return None
    return user.get(security_attribute)
