"""
Integration test: real Ollama, confirms a real model can invoke a
"create" named action and the result is a genuinely well-formed
proposal -- the one real, still-open gap this project had. Two
mechanisms were found and fixed while building named actions
("user.security_value" and writing to a type's own id_field, see
core/ontology/write_mediator.py's _resolve_mutation_value() and
core/ontology/schema.py's get_column_for_field()), but neither had
ever been exercised by a REAL, freely-reasoning model before this --
only unit tests and direct scratch verification confirmed them.
SLOW, requires Ollama.

This was originally test_real_model_produces_a_well_formed_write_
proposal, testing an "update" action -- but once user_eve gained the
SAME UpdateCustomerName action tests/integration/test_named_actions_
e2e.py already proves end to end (a real model producing a well-formed
propose_action for it), that test would have become a pure duplicate.
Repurposed instead to close the genuinely open gap: CreateCustomer
exercises BOTH fixes together -- the model supplies customer_id (the
id_field) and name/email directly, and region (the MAC security
field) is populated automatically from the ACTING user's own value,
never something the model chooses.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment. user_eve (see fixtures/policy.yaml) has the
"editor" role, granting execute:CreateCustomer.

Deliberately does NOT confirm/execute the proposed action -- that flow
(propose -> confirm -> a real database change) is already proven
end-to-end elsewhere (tests/integration/test_api.py,
tests/integration/test_named_actions_e2e.py); this test is
specifically about whether the model's OWN CHOICE of parameters is
well-formed enough to even REACH the pending stage, with the
mutations correctly resolved -- including the two fields the model
never directly names at all (region, via user.security_value).
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.write_mediator import WriteMediator

QUERY_TEXT = (
    "Create a new customer with customer_id 'cust_999', "
    "name 'Grace Hopper', and email 'grace@example.com'."
)


@pytest.mark.integration
def test_real_model_produces_a_well_formed_create_action_proposal(deployment, mediator):
    write_mediator = WriteMediator(mediator, deployment.roles, deployment.action_types)
    loop = AgentLoop.from_deployment(deployment, mediator, write_mediator=write_mediator)
    user_record = resolve_user_record(deployment.users, "user_eve", deployment.security_attribute)

    result = loop.run(user_record, QUERY_TEXT)

    # Same diagnostic-print pattern as test_field_denial_e2e.py -- a
    # genuine failure here (the model never producing a valid proposal)
    # is real, informative information about model capability, worth
    # seeing either way, not just on a hard failure.
    print(f"\n[diagnostic] pending_write: {result.pending_write}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    assert result.pending_write is not None, (
        "Expected the real model to produce a well-formed propose_action step "
        f"for CreateCustomer, but it never reached the pending stage. Gathered: {result.gathered}"
    )
    sub_write = result.pending_write.sub_writes[0]
    assert sub_write.object_type == "Customer"
    assert sub_write.operation == "create"

    # THE model's own, explicit choices -- it read the query and
    # supplied exactly these three parameters correctly.
    assert sub_write.changes["customer_id"] == "cust_999"
    assert sub_write.changes["name"] == "Grace Hopper"
    assert sub_write.changes["email"] == "grace@example.com"

    # THE thing this test actually exists to prove: "region" was
    # resolved automatically from user_eve's OWN security value --
    # the model never saw or chose this field at all, yet it's present
    # and correct in the resolved mutations.
    assert sub_write.changes["region"] == user_record.security_value
