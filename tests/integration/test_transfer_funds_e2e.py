"""
Integration test: real Ollama, confirms a REAL model can discover,
correctly describe to itself, and successfully invoke a GENUINELY
MULTI-OBJECT named action (TransferFunds, two sub_writes, both
Account) -- the one genuinely unproven question the whole sub_writes/
write_log_batches mechanism still had. Everything about the mechanism
ITSELF (multi-object apply, sorted-order locking, the resolved-id
duplicate check, RBAC/MAC per sub_write) is already thoroughly proven
by tests/unit/test_transfer_funds.py (fully scripted, no model, this
file's own direct counterpart) and, at the lower, synthetic-fixture
level, tests/unit/test_write_log_batches.py, tests/unit/test_confirm_
and_execute_batches.py, tests/unit/test_write_log_resume.py. This is
the first time a real model's own reasoning ever sees a genuinely
multi-object propose_action call at all -- not just a single-object
one (already proven by tests/integration/test_named_actions_e2e.py).

QUERY_TEXT states the EXACT target balance for both accounts directly
-- deliberately NOT phrased as "transfer $50," which would additionally
require the model to correctly compute new_from_balance/new_to_balance
via arithmetic on whatever it reads as each account's current balance.
Mutations only ever "set" a value (see ontology_schema.yaml's own
comment on TransferFunds for why there's no increment/decrement
mutation kind) -- the CALLER must already know the new balances, so a
real usage of this action always looks like this query, not a raw
delta. Keeping that variable out keeps THIS test's own one genuinely
unproven question isolated: can a real model discover and correctly
invoke an action spanning two different real objects, matching
test_named_actions_e2e.py's own stated discipline for exactly this
reason.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, a fresh database per test. user_henry has
the dedicated "accountant" role (execute:TransferFunds), NOT an
extension of user_eve/editor's existing grants -- see policy.yaml's
own comment for why (a NEW grant on an EXISTING, already-tested user
silently changes what that user's prompt shows to every OTHER test
already relying on it). SLOW, requires Ollama.
"""

import pytest

from tests.integration.conftest import propose_named_action

QUERY_TEXT = (
    "Using the TransferFunds action, update account acc_checking to a "
    "new balance of 450.00 and account acc_savings to a new balance of 1050.00."
)


@pytest.mark.integration
def test_real_model_invokes_a_genuinely_multi_object_action(deployment, mediator):
    write_mediator, pending, user_record = propose_named_action(deployment, mediator, QUERY_TEXT, "user_henry")

    # THE first real, unproven claim: a REAL model's own propose_action
    # call produced TWO sub_writes, touching TWO genuinely different
    # real Account objects -- not one, not the same object twice.
    assert len(pending.sub_writes) == 2
    touched_ids = {sw.object_id for sw in pending.sub_writes}
    assert touched_ids == {"acc_checking", "acc_savings"}, (
        f"Expected the model to touch exactly acc_checking and acc_savings, "
        f"got {touched_ids}"
    )
    for sub_write in pending.sub_writes:
        assert set(sub_write.changes.keys()) == {"balance"}

    outcome = write_mediator.confirm_and_execute(pending, approved=True)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome is not None
    assert set(outcome["object_ids"]) == {"acc_checking", "acc_savings"}

    # THE second, real thing this test exists to prove: the REAL
    # database, read back independently of the write path, reflects
    # the model's OWN proposed values for BOTH accounts -- not a
    # hardcoded expectation about exactly how the model phrased its
    # own parameters, mirroring test_named_actions_e2e.py's own
    # "proposed_name" pattern.
    for sub_write in pending.sub_writes:
        proposed_balance = sub_write.changes["balance"]
        real_balance = mediator.get_field(user_record, "Account", sub_write.object_id, "balance")
        assert real_balance == proposed_balance, (
            f"Expected the database's {sub_write.object_id} balance to reflect the "
            f"model's own proposed value {proposed_balance!r}, but found {real_balance!r}"
        )


@pytest.mark.integration
def test_real_model_transfer_rejected_leaves_both_accounts_unchanged(deployment, mediator):
    write_mediator, pending, user_record = propose_named_action(deployment, mediator, QUERY_TEXT, "user_henry")

    outcome = write_mediator.confirm_and_execute(pending, approved=False)
    print(f"[diagnostic] confirm_and_execute outcome: {outcome}")

    assert outcome is None

    real_checking = mediator.get_field(user_record, "Account", "acc_checking", "balance")
    real_savings = mediator.get_field(user_record, "Account", "acc_savings", "balance")
    assert real_checking == 500.0, (
        f"Expected acc_checking to remain at its original seed balance after "
        f"rejection, but found {real_checking!r}"
    )
    assert real_savings == 1000.0, (
        f"Expected acc_savings to remain at its original seed balance after "
        f"rejection, but found {real_savings!r}"
    )


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# IMPORTANT CAVEAT: this file was built and verified as thoroughly as
# possible WITHOUT a real Ollama server -- none was available in the
# environment this was written in (checked directly: neither `which
# ollama` nor a curl to localhost:11434 found anything). What WAS
# verified directly: both tests correctly COLLECT; both fail FAST
# (0.08s) and CLEANLY with a clear diagnostic assertion message, not a
# hang or a confusing raw traceback, when Ollama is genuinely
# unreachable (core/llm/agent_step_prompt.py's own request/parse-
# failure handling already degrades gracefully to gathered=[],
# pending_write=None, and this file's own propose_named_action() call
# asserts on exactly that) -- so this file is SAFE to leave for a
# human to run for real, not a risk of hanging CI or silently passing
# for the wrong reason. What was NOT verified: whether a real model
# actually succeeds at the task this file describes (discovering and
# correctly invoking a genuinely two-object action). That is this
# whole file's actual point, and remains genuinely open until someone
# runs it against a real Ollama instance.
# - Getting all the way to the Ollama connection attempt (rather than
#   failing earlier, e.g. on a schema/fixture problem) DOES confirm
#   the real fixture setup -- tests/integration/fixtures/schema.sql's
#   new accounts table, ontology_schema.yaml's new Account/
#   TransferFunds, policy.yaml's new accountant/user_henry -- all load
#   correctly through the REAL conftest.py path, not just an ad-hoc
#   verification script. That part is solid.
# - If this is ever revisited and a real model DOESN'T reliably
#   produce a well-formed two-object proposal from QUERY_TEXT as
#   written, the most likely fix is making the query even more
#   explicit/structured (the model-facing prompt for a multi-object
#   action -- see core/llm/agent_step_prompt.py's own hint-building
#   logic -- has itself only ever been exercised by single-object
#   named actions before this file existed) before assuming the
#   underlying mechanism itself has a bug; tests/unit/test_transfer_
#   funds.py already proves the mechanism's own correctness
#   independent of any model's own reliability.
