"""
auth.py  (the policy CHECK -- generic mechanism, no org data)

Answers two questions, given a user registry:
  - authorize(): can this user call this action at all?
  - get_user_security_value(): what's this user's row-level access
    value, for whatever attribute the deployment's policy.yaml declares
    (e.g. "region") -- this file doesn't assume the attribute is called
    "region" specifically; the deployment supplies that name.

This file only knows the SHAPE user data must have, never its actual
contents -- that's deployments/<org>/policy.yaml's job.

Called by: gateway.py, and (for get_user_security_value) test_run.py
           and tests/integration/ directly
"""


def authorize(users: dict, user_id: str, action_id: str) -> bool:
    user = users.get(user_id)
    if user is None:
        return False
    return action_id in user["allowed_actions"]


def get_user_security_value(users: dict, user_id: str, security_attribute: str) -> str | None:
    user = users.get(user_id)
    if user is None:
        return None
    return user.get(security_attribute)
