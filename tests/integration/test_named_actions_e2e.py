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

from tests.integration.conftest import propose_named_action

QUERY_TEXT = "Update cust_001's name to 'Ada Lovelace'."


@pytest.mark.integration
def test_real_model_invokes_named_action_and_it_actually_changes_the_database(deployment, mediator, write_adapters):
    write_mediator, pending, user_record = propose_named_action(deployment, mediator, write_adapters, QUERY_TEXT)

    # THE first real, unproven claim: the PendingWrite this produced
    # genuinely came through the resolved-mutations path, not a raw
    # field the model somehow injected directly -- "name" is the
    # action's own declared mutation target, resolved from whatever
    # parameter the model chose to supply.
    assert set(pending.sub_writes[0].changes.keys()) == {"name"}
    proposed_name = pending.sub_writes[0].changes["name"]

    outcome = write_mediator.confirm_and_execute(pending, approved=True)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome == {"status": "written", "object_ids": [pending.sub_writes[0].object_id]}

    # THE second, real thing this test exists to prove: the REAL
    # database, read back independently of the write path, reflects
    # the model's OWN chosen value for its OWN chosen parameter -- not
    # a hardcoded expectation, since the model's exact phrasing (and
    # even which parameter NAME it used internally) is its own choice.
    real_value = mediator.get_field(user_record, "Customer", pending.sub_writes[0].object_id, "name")
    assert real_value == proposed_name, (
        f"Expected the database to reflect the model's own proposed value "
        f"{proposed_name!r}, but found {real_value!r}"
    )


@pytest.mark.integration
def test_real_model_proposal_rejected_leaves_database_unchanged(deployment, mediator, write_adapters):
    write_mediator, pending, user_record = propose_named_action(deployment, mediator, write_adapters, QUERY_TEXT)

    outcome = write_mediator.confirm_and_execute(pending, approved=False)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome is None

    real_value = mediator.get_field(user_record, "Customer", pending.sub_writes[0].object_id, "name")
    assert real_value == "Ada Okafor", (
        f"Expected the database to remain at the original seed value "
        f"after rejection, but found {real_value!r}"
    )


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# RESOLVED (kept for history):
# - A prior pass migrating PendingWrite's own object_id retirement
#   fixed the outcome assertion's own "object_id" reference in this
#   file, but MISSED two other, identical stale references (both in
#   get_field() calls, one per test function) -- pending.object_id,
#   which does not exist on PendingWrite at all (confirmed directly:
#   PendingWrite.__dataclass_fields__ has no such key). This went
#   uncaught for a real reason, not carelessness: this whole file
#   requires a real, locally-running Ollama server, which was not
#   available in the environment(s) that ran the fast suite throughout
#   that migration, so it was never actually exercised. Found and
#   fixed by directly checking PendingWrite's own real attributes,
#   not assumed from the surrounding code's own apparent intent.
#   Fixed to pending.sub_writes[0].object_id, matching every other
#   already-migrated reference in this same file.
