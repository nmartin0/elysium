"""
Integration tests: real Ollama, confirms the FULL "create" action
chain -- a real model's own proposal for a NEW object, confirmed or
rejected, actually (or correctly does NOT) create a real row in the
database. Completes the create lifecycle proof that test_write_
proposal_e2e.py deliberately stops short of (it proves the proposal
itself is well-formed, but never confirms/executes it) -- this is the
first time a real model's OWN "create" action gets confirmed and
actually reaches the database, not just proposed.

This file previously duplicated test_named_actions_e2e.py once
user_eve gained the same UpdateCustomerName action that test already
proves end to end -- repurposed instead to close the genuinely open
part of the create lifecycle: does the FULL chain (a real model's own
customer_id/name/email choices, PLUS the automatically-resolved
"region" via user.security_value) actually persist correctly, and does
a rejection genuinely create nothing at all.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, a fresh database per test. user_eve has the
"editor" role, granting execute:CreateCustomer.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.write_mediator import WriteMediator

QUERY_TEXT = (
    "Create a new customer with customer_id 'cust_999', "
    "name 'Grace Hopper', and email 'grace@example.com'."
)


def _propose(deployment, mediator):
    write_mediator = WriteMediator(mediator, deployment.roles, deployment.action_types)
    loop = AgentLoop.from_deployment(deployment, mediator, write_mediator=write_mediator)
    user_record = resolve_user_record(deployment.users, "user_eve", deployment.security_attribute)

    result = loop.run(user_record, QUERY_TEXT)
    print(f"\n[diagnostic] pending_write: {result.pending_write}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    assert result.pending_write is not None, (
        "Expected the real model to produce a well-formed propose_action step "
        f"for CreateCustomer, but it never reached the pending stage. Gathered: {result.gathered}"
    )
    return write_mediator, result.pending_write, user_record


@pytest.mark.integration
def test_real_model_create_action_approved_actually_creates_the_row(deployment, mediator):
    write_mediator, pending, user_record = _propose(deployment, mediator)
    proposed_customer_id = pending.changes["customer_id"]
    proposed_name = pending.changes["name"]
    proposed_email = pending.changes["email"]

    outcome = write_mediator.confirm_and_execute(pending, approved=True)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome == {"status": "written", "object_id": proposed_customer_id}

    # THE thing this test exists to prove: the REAL database, read back
    # independently of the write path, reflects the model's OWN chosen
    # values for the fields it named directly...
    assert mediator.get_field(user_record, "Customer", proposed_customer_id, "name") == proposed_name
    assert mediator.get_field(user_record, "Customer", proposed_customer_id, "email") == proposed_email

    # ...AND the field it never named at all -- "region" -- correctly
    # persisted from the ACTING user's own security value, not
    # anything the model chose or even saw.
    assert mediator.get_field(user_record, "Customer", proposed_customer_id, "region") == user_record.security_value


@pytest.mark.integration
def test_real_model_create_action_rejected_creates_nothing(deployment, mediator):
    write_mediator, pending, user_record = _propose(deployment, mediator)
    proposed_customer_id = pending.changes["customer_id"]

    outcome = write_mediator.confirm_and_execute(pending, approved=False)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome is None

    # THE thing this test exists to prove: a rejected "create" leaves
    # NO row behind at all -- not a partial one, not one with only
    # SOME fields set. search_object() finding nothing is the correct,
    # genuine proof no object with this id exists.
    found = mediator.search_object(user_record, "Customer", {"customer_id": proposed_customer_id})
    assert found == [], (
        f"Expected a rejected create to leave NO customer behind, "
        f"but search_object found: {found}"
    )
