"""
Integration test: confirms cross-region (or whatever attribute a
deployment's policy.yaml declares) blocking holds through the full
LLM-driven agent loop -- not just the direct mediator calls already
covered by tests/unit/test_mediator.py. SLOW, requires Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, not the real deployment/ folder a human
explores. The query text ("cust_003") is this fixture's specific data.

Requests isolated_audit_log (see conftest.py) so this test's real
access-denial activity doesn't fall back to the actual deployment/
var/log/audit.log a human might be reading, and can't leak its own
logging configuration into whatever test runs next in the same pytest
process.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record


@pytest.mark.integration
def test_cross_region_query_returns_no_real_transaction_data(deployment, mediator, isolated_audit_log):
    # user_alice is us-west; cust_003 is us-east -- every field access
    # should be blocked, regardless of what the LLM tries.
    loop = AgentLoop.from_deployment(deployment, mediator)
    user_record = resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)
    agent_result = loop.run(user_record, "What are cust_003's recent transactions?")
    real_data = AgentLoop.filter_real_data(agent_result.gathered)

    # No matter what the LLM attempted, nothing real about cust_003
    # should ever come back -- every result must be None (a blocked
    # get_field) or an empty list (a blocked search_object).
    for item in real_data:
        field_result = item.get("result")
        assert field_result is None or field_result == [], (
            f"Unexpected non-empty cross-region data leaked: {item}"
        )
