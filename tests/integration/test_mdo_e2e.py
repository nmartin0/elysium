"""
Integration test: real Ollama, confirms a real model transparently
reads an MDO (multi-datasource object type) field -- one backed by a
GENUINELY SEPARATE silo than the rest of its object type, with zero
indication of this in the model's own prompt. Proves what
tests/unit/test_mdo.py already proved mechanically (with a scripted
model) also holds with a real, freely-reasoning one. SLOW, requires
Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, now with THREE genuinely separate SQLite
databases. Customer.risk_score is backed by risk_sql, while the rest
of Customer (region, name, email) is backed by primary_sql -- the
model has no way to know this from the question alone
(_build_system_prompt() never renders storage/additional_storage into
the prompt at all -- confirmed directly in this file's own fixture
verification before the real test was ever run, not assumed).

Deliberately keeps the SAME real-world mismatches
tests/unit/test_mdo.py proved mechanically, not a simplified version:
risk_sql's own id_column is "cust_ref" (not "customer_id"), and its
own column is "score_val" (not "risk_score") -- both resolved
correctly and invisibly to the model.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record


@pytest.mark.integration
def test_real_model_transparently_reads_an_mdo_field(deployment, mediator):
    loop = AgentLoop.from_deployment(deployment, mediator)
    user_record = resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)

    result = loop.run(user_record, "What is cust_001's risk score?")

    print(f"\n[diagnostic] full gathered steps: {result.gathered}")

    # THE thing this test exists to prove: the model reached
    # risk_score and got the REAL value back -- a value that could
    # only have come from risk_sql, a database genuinely separate from
    # where the rest of Customer lives, resolved transparently.
    risk_score_reads = [
        item for item in result.gathered
        if item.get("step") == "get_field" and item.get("field_name") == "risk_score"
    ]
    assert len(risk_score_reads) > 0, (
        f"Expected the model to read risk_score, but it never did. Gathered: {result.gathered}"
    )
    assert risk_score_reads[0]["result"] == 0.35, (
        f"Expected the real seed value 0.35 (from risk_sql's customer_risk table, "
        f"cust_ref='cust_001'), but got: {risk_score_reads[0]['result']}"
    )
