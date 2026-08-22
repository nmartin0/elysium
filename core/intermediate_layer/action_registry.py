"""
action_registry.py  (the dispatch MECHANISM -- generic, no org data)

Given a deployment's own action map (action_id -> adapter function) and
a chosen action_id, calls the right function. Same fix as auth.py: this
file used to import acme_corp's adapter directly, which baked one
deployment's specifics into supposedly-portable code. Now it just knows
HOW to dispatch, not WHICH functions exist.

Called by: gateway.py (after authorization succeeds), passed the calling
           deployment's own actions dict as an argument.
"""


def dispatch(actions: dict, action_id: str, user_region: str, params: dict) -> list[dict]:
    fn = actions.get(action_id)
    if fn is None:
        raise ValueError(f"Unknown action_id: {action_id}")
    return fn(user_region, **params)
