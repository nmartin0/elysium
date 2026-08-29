"""
Integration tests: real Ollama, confirms the FULL write chain -- a real
model's own proposal, confirmed or rejected, actually (or correctly
does NOT) change the real database -- not just that the model can
PRODUCE a well-formed proposal (already proven by
tests/integration/test_write_proposal_e2e.py, which deliberately stops
before confirming) and not just that confirm_and_execute() itself
works correctly given a SCRIPTED proposal (already proven by
tests/unit/test_write_mediator.py, and by tests/integration/test_api.py
with a mocked LLM). SLOW, requires Ollama.

This is the one remaining link nothing else in this project's test
suite has proven together: a real model's own field names, own object
id, and own proposed value, flowing through WriteMediator's real
RBAC/MAC checks and the database's real atomic conditional write, with
the actual resulting (or unchanged) row read back afterward.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, a fresh database per test. user_eve has the
"editor" role, genuinely granting write:Customer.name.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.write_mediator import WriteMediator

QUERY_TEXT = "Update cust_001's name to 'Ada Lovelace'."


def _propose(deployment, mediator):
    write_mediator = WriteMediator(mediator, deployment.roles)
    loop = AgentLoop.from_deployment(deployment, mediator, write_mediator=write_mediator)
    user_record = resolve_user_record(deployment.users, "user_eve", deployment.security_attribute)

    result = loop.run(user_record, QUERY_TEXT)
    print(f"\n[diagnostic] pending_write: {result.pending_write}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    assert result.pending_write is not None, (
        "Expected the real model to produce a well-formed propose_write step, "
        f"but it never reached the pending stage. Gathered: {result.gathered}"
    )
    return write_mediator, result.pending_write, user_record


@pytest.mark.integration
def test_real_model_proposal_approved_actually_changes_the_database(deployment, mediator):
    write_mediator, pending, user_record = _propose(deployment, mediator)
    proposed_name = pending.changes["name"]

    outcome = write_mediator.confirm_and_execute(pending, approved=True)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome == {"status": "written", "object_id": pending.object_id}

    # THE thing this test exists to prove: the REAL database, read back
    # independently of the write path, reflects the model's OWN
    # proposed value -- not a hardcoded expectation, since the model's
    # exact phrasing is its own choice, not scripted.
    real_value = mediator.get_field(user_record, "Customer", pending.object_id, "name")
    assert real_value == proposed_name, (
        f"Expected the database to reflect the model's own proposed value "
        f"{proposed_name!r}, but found {real_value!r}"
    )


@pytest.mark.integration
def test_real_model_proposal_rejected_leaves_database_unchanged(deployment, mediator):
    write_mediator, pending, user_record = _propose(deployment, mediator)

    outcome = write_mediator.confirm_and_execute(pending, approved=False)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome is None

    # THE thing this test exists to prove: a rejected real-model
    # proposal leaves the real database GENUINELY untouched -- the
    # original seed value, not the model's proposed one.
    real_value = mediator.get_field(user_record, "Customer", pending.object_id, "name")
    assert real_value == "Ada Okafor", (
        f"Expected the database to remain at the original seed value "
        f"after rejection, but found {real_value!r}"
    )
