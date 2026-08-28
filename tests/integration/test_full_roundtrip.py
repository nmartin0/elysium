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
This same isolated log is ALSO what makes the log-content assertion
below meaningful -- asserting against a commingled log would be
fragile and order-dependent, exactly what we were careful to avoid.

Run with: python3 -m pytest tests/integration/ -v -m integration
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.deployment_loader import build_llm_adapter
from core.llm.synthesis_prompt import synthesize_insight

from conftest import read_audit_log


def _run(deployment, mediator, user_id: str, query_text: str) -> str:
    loop = AgentLoop.from_deployment(deployment, mediator)
    synthesis_client = build_llm_adapter(deployment, deployment.synthesis_model)

    user_record = resolve_user_record(deployment.users, user_id, deployment.security_attribute)
    result = loop.run(user_record, query_text)
    real_data = AgentLoop.filter_real_data(result.gathered)

    return synthesize_insight(synthesis_client, query_text, real_data, result.hit_max_hops)


@pytest.mark.integration
def test_same_region_query_returns_correct_transactions(deployment, mediator, isolated_audit_log):
    answer = _run(deployment, mediator, "user_alice", "What are cust_001's recent transactions?")
    assert "49.99" in answer
    assert "199" in answer

    # THE audit-log proof: this exact session's ALLOWED access to
    # cust_001 was genuinely logged with BOTH gates independently
    # evaluated and passing -- not just "the answer happened to look
    # right," but the access-control layer's own record confirming why.
    log_entries = read_audit_log(isolated_audit_log)
    allowed_customer_checks = [
        entry for entry in log_entries
        if entry.get("stage") == "access_check" and entry.get("object_type") == "Customer"
        and entry.get("object_id") == "cust_001" and entry.get("allowed") is True
    ]
    assert len(allowed_customer_checks) > 0, "Expected at least one logged, allowed access check for cust_001"
    for entry in allowed_customer_checks:
        assert entry["mac_allowed"] is True
        assert entry["rbac_allowed"] is True
