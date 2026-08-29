"""
Integration test: real Ollama, confirms a REAL model can discover,
correctly describe to itself, and successfully invoke a NAMED action
(propose_action, action-types-redesign branch) -- the one genuinely
unproven question this whole mechanism still had. Everything else
about named actions (propose_action() itself, submission criteria,
mutation resolution, RBAC/MAC independence, the distinct
rejected_business_rule category) is already thoroughly proven by
tests/unit/test_named_actions.py, tests/unit/test_agentic_loop_named_
actions.py, and tests/unit/test_agent_step_prompt_named_actions.py --
all with SCRIPTED model responses. This is the first time a real
model's own reasoning ever sees the propose_action vocabulary at all.

Deliberately mirrors tests/integration/test_write_confirmation_e2e.py's
structure closely -- same shape of proof (a real model's own proposal,
confirmed, actually changes the real database), just through the NEW
proposal path instead of the old one. SLOW, requires Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, a fresh database per test. user_eve has the
"editor" role, granting execute:UpdateCustomerName (originally proven
with a dedicated user_grace/name_updater, specifically to avoid
changing an existing, already-tested user's prompt mid-branch -- see
ontology_schema.yaml's own comment for why that isolation concern no
longer applied once the full migration pass deliberately moved editor
onto the same execute: grant, and user_grace was consolidated away).
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.write_mediator import WriteMediator

QUERY_TEXT = "Update cust_001's name to 'Ada Lovelace'."


def _propose(deployment, mediator):
    write_mediator = WriteMediator(mediator, deployment.roles, deployment.action_types)
    loop = AgentLoop.from_deployment(deployment, mediator, write_mediator=write_mediator)
    user_record = resolve_user_record(deployment.users, "user_eve", deployment.security_attribute)

    result = loop.run(user_record, QUERY_TEXT)
    print(f"\n[diagnostic] pending_write: {result.pending_write}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    assert result.pending_write is not None, (
        "Expected the real model to discover and produce a well-formed "
        f"propose_action step, but it never reached the pending stage. "
        f"Gathered: {result.gathered}"
    )
    return write_mediator, result.pending_write, user_record


@pytest.mark.integration
def test_real_model_invokes_named_action_and_it_actually_changes_the_database(deployment, mediator):
    write_mediator, pending, user_record = _propose(deployment, mediator)

    # THE first real, unproven claim: the PendingWrite this produced
    # genuinely came through the resolved-mutations path, not a raw
    # field the model somehow injected directly -- "name" is the
    # action's own declared mutation target, resolved from whatever
    # parameter the model chose to supply.
    assert set(pending.changes.keys()) == {"name"}
    proposed_name = pending.changes["name"]

    outcome = write_mediator.confirm_and_execute(pending, approved=True)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome == {"status": "written", "object_id": pending.object_id}

    # THE second, real thing this test exists to prove: the REAL
    # database, read back independently of the write path, reflects
    # the model's OWN chosen value for its OWN chosen parameter -- not
    # a hardcoded expectation, since the model's exact phrasing (and
    # even which parameter NAME it used internally) is its own choice.
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

    real_value = mediator.get_field(user_record, "Customer", pending.object_id, "name")
    assert real_value == "Ada Okafor", (
        f"Expected the database to remain at the original seed value "
        f"after rejection, but found {real_value!r}"
    )
