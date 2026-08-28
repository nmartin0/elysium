"""
Integration test: real Ollama, confirms a real model produces a
WELL-FORMED propose_write step when asked to make a plausible change --
not just that WriteMediator correctly REJECTS malformed/unauthorized
ones when scripted to (already proven by
tests/unit/test_write_mediator.py). SLOW, requires Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment. user_eve (see fixtures/policy.yaml) has the
"editor" role, genuinely granting write:Customer.name.

Deliberately does NOT confirm/execute the proposed write -- that flow
(propose -> confirm -> a real database change) is already proven
end-to-end elsewhere (tests/integration/test_api.py); this test is
specifically about whether the model's OWN CHOICE of object_type,
object_id, and field name is well-formed enough to even REACH the
pending stage at all, not about the confirmation flow itself.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.write_mediator import WriteMediator


@pytest.mark.integration
def test_real_model_produces_a_well_formed_write_proposal(deployment, mediator):
    write_mediator = WriteMediator(mediator, deployment.roles)
    loop = AgentLoop.from_deployment(deployment, mediator, write_mediator=write_mediator)
    user_record = resolve_user_record(deployment.users, "user_eve", deployment.security_attribute)

    result = loop.run(user_record, "Update cust_001's name to 'Ada Lovelace'.")

    # Same diagnostic-print pattern as test_field_denial_e2e.py -- a
    # genuine failure here (the model never producing a valid proposal)
    # is real, informative information about model capability, worth
    # seeing either way, not just on a hard failure.
    print(f"\n[diagnostic] pending_write: {result.pending_write}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    assert result.pending_write is not None, (
        "Expected the real model to produce a well-formed propose_write step, "
        f"but it never reached the pending stage. Gathered: {result.gathered}"
    )
    assert result.pending_write.object_type == "Customer"
    assert result.pending_write.object_id == "cust_001"
    assert "name" in result.pending_write.changes
    assert result.pending_write.changes["name"]  # non-empty value
