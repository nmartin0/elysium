"""
Integration test: confirms cross-region (or whatever attribute a
deployment's policy.yaml declares) blocking holds through the full
LLM-driven agent loop -- not just the direct engine calls already
covered by tests/unit/test_sql_adapter.py. SLOW, requires Ollama.

Deployment is dynamic (see conftest.py) -- defaults to acme_corp. The
query text ("cust_003") is acme_corp-specific data.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import get_user_security_value


@pytest.mark.integration
def test_cross_region_query_returns_no_real_transaction_data(deployment, engine):
    # user_alice is us-west; cust_003 is us-east -- every field access
    # should be blocked, regardless of what the LLM tries.
    loop = AgentLoop.from_deployment(deployment, engine)
    user_security_value = get_user_security_value(deployment.users, "user_alice", deployment.security_attribute)
    gathered = loop.run(user_security_value, "What are cust_003's recent transactions?")
    real_data = AgentLoop.filter_real_data(gathered)

    # No matter what the LLM attempted, nothing real about cust_003
    # should ever come back -- every result must be None (a blocked
    # get_field) or an empty list (a blocked search_object).
    for item in real_data:
        result = item.get("result")
        assert result is None or result == [], (
            f"Unexpected non-empty cross-region data leaked: {item}"
        )
