"""
Integration test: real Ollama, full agent loop -> synthesis. SLOW
(multiple LLM calls) and requires Ollama running locally with the
configured model already pulled.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, not the real deployment/ folder a human
explores. Assertions reference this fixture's known dev data.

Requests isolated_audit_log (see conftest.py) so this test's real
write/read activity doesn't fall back to the actual deployment/var/log/
audit.log a human might be reading, and can't leak its own logging
configuration into whatever test runs next in the same pytest process.

Run with: python3 -m pytest tests/integration/ -v -m integration
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.deployment_loader import build_llm_adapter
from core.llm.synthesis_prompt import synthesize_insight


def _run(deployment, mediator, user_id: str, query_text: str) -> str:
    loop = AgentLoop.from_deployment(deployment, mediator)
    synthesis_client = build_llm_adapter(deployment, deployment.synthesis_model)

    user_record = resolve_user_record(deployment.users, user_id, deployment.security_attribute)
    result = loop.run(user_record, query_text)
    real_data = AgentLoop.filter_real_data(result.gathered)

    return synthesize_insight(synthesis_client, query_text, real_data)


@pytest.mark.integration
def test_same_region_query_returns_correct_transactions(deployment, mediator, isolated_audit_log):
    answer = _run(deployment, mediator, "user_alice", "What are cust_001's recent transactions?")
    assert "49.99" in answer
    assert "199" in answer
