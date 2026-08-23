"""
Integration test: real Ollama, full agent loop -> synthesis. SLOW
(multiple LLM calls) and requires Ollama running locally with the
configured model already pulled.

Deployment is dynamic (see conftest.py) -- defaults to acme_corp.
Assertions still reference acme_corp's known dev-fixture data, since
fully deployment-agnostic assertions would require each deployment to
declare its own expected test scenarios (a future enhancement).

Run with: TEST_DEPLOYMENT=acme_corp python3 -m pytest tests/integration/ -v -m integration
(TEST_DEPLOYMENT is optional -- acme_corp is the default)

Promoted from scratch/scratch_full_roundtrip.py.
"""

import pytest

from core.agent.loop import run_agent_loop
from core.llm.synthesis_prompt import synthesize_insight
from core.intermediate_layer.auth import get_user_security_value


def _run(deployment, ontology_adapter, user_id: str, query_text: str) -> str:
    user_security_value = get_user_security_value(
        deployment.USERS, user_id, deployment.SECURITY_ATTRIBUTE
    )
    gathered = run_agent_loop(
        user_region=user_security_value,
        query_text=query_text,
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
    return synthesize_insight(
        query_text, real_data,
        model=deployment.SYNTHESIS_MODEL,
        ollama_url=deployment.OLLAMA_URL,
        timeout_seconds=deployment.REQUEST_TIMEOUT_SECONDS,
    )


@pytest.mark.integration
def test_same_region_query_returns_correct_transactions(deployment, ontology_adapter):
    answer = _run(deployment, ontology_adapter, "user_alice", "What are cust_001's recent transactions?")
    assert "49.99" in answer
    assert "199" in answer  # allow "199.00" or "199"
