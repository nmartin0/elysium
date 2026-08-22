"""
policy.py  (acme_corp-specific -- NOT portable to other orgs)

Which users exist in this deployment, their region, and which actions
they're allowed to call. This used to live inside core/intermediate_layer/
auth.py -- moved here once we recognized it as org data, not mechanism.

For this prototype it's a hardcoded dict. In a real deployment this
becomes a database table or an external identity/policy system -- only
this file would need to change; core/intermediate_layer/auth.py wouldn't.

Called by: test_run.py (passed into gateway.handle_request as `users`)
"""

USERS = {
    "user_alice": {
        "region": "us-west",
        "allowed_actions": {"get_customer_transactions"},
    },
    "user_bob": {
        "region": "us-east",
        "allowed_actions": {"get_customer_transactions"},
    },
    "user_carol": {
        "region": "eu",
        "allowed_actions": set(),
    },
}
