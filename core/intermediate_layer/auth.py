"""
auth.py  (the policy CHECK -- generic mechanism, no org data)

Answers exactly one question: given a user registry and (user_id,
action_id), is this user allowed to do this?

This file used to also hold the hardcoded user data itself -- that was a
mistake once org-specific data entered the picture. Which users exist,
their regions, and their permissions is data that belongs to a specific
deployment (see deployments/acme_corp/policy.py), not to portable core
code. This file only knows the SHAPE that data must have, never its
actual contents.

Called by: gateway.py (step 1, before anything else happens), passed the
           calling deployment's own user registry as an argument.
"""


def authorize(users: dict, user_id: str, action_id: str) -> bool:
    user = users.get(user_id)
    if user is None:
        return False
    return action_id in user["allowed_actions"]


def get_user_region(users: dict, user_id: str) -> str | None:
    user = users.get(user_id)
    if user is None:
        return None
    return user["region"]
