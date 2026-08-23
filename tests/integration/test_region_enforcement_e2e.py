"""
Integration test: confirms cross-region (or whatever attribute a
deployment's policy.yaml declares) blocking holds through the full
LLM-driven agent loop -- not just the direct sql_adapter calls already
covered by tests/unit/test_sql_adapter.py. SLOW, requires Ollama.

Deployment is dynamic (see conftest.py) -- defaults to acme_corp. The
query text ("cust_003") is acme_corp-specific data; a different
deployment would need its own version of this test with its own known
cross-boundary object.

Promoted from scratch/scratch_debug_carol.py.
"""

import pytest

from core.agent.loop import run_agent_loop
from core.intermediate_layer.auth import get_user_security_value


@pytest.mark.integration
def test_cross_region_query_returns_no_real_transaction_data(deployment, ontology_adapter):
    # user_alice is us-west; cust_003 is us-east -- every field access
    # should be blocked, regardless of what the LLM tries.
    user_security_value = get_user_security_value(
        deployment.USERS, "user_alice", deployment.SECURITY_ATTRIBUTE
    )
    gathered = run_agent_loop(
        user_region=user_security_value,
        query_text="What are cust_003's recent transactions?",
        schema=deployment.SCHEMA,
        search_fn=ontology_adapter.search_object,
        get_field_fn=ontology_adapter.get_field,
        model=deployment.STEP_MODEL,
        ollama_url=deployment.OLLAMA_URL,
        timeout_seconds=deployment.REQUEST_TIMEOUT_SECONDS,
        max_hops=deployment.MAX_HOPS,
        max_consecutive_duplicates=deployment.MAX_CONSECUTIVE_DUPLICATES,
        max_consecutive_invalid_steps=deployment.MAX_CONSECUTIVE_INVALID_STEPS,
    )

    real_data = [
        item for item in gathered
        if item["step"] not in ("rejected_duplicate", "completeness_check", "rejected_invalid_step")
    ]

    # No matter what the LLM attempted, nothing real about cust_003
    # should ever come back -- every result must be None (a blocked
    # get_field) or an empty list (a blocked search_object).
    for item in real_data:
        result = item.get("result")
        assert result is None or result == [], (
            f"Unexpected non-empty cross-region data leaked: {item}"
        )
