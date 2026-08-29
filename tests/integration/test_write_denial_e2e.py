"""
Integration test: real Ollama, confirms a real model's write proposal
is genuinely BLOCKED, end to end, when the user has no write: grant at
all -- the security-critical denial counterpart to
tests/integration/test_write_confirmation_e2e.py's success paths.
Nothing in this project's suite has proven this with a real,
freely-reasoning model before -- tests/unit/test_write_mediator.py's
denial tests all use scripted proposals, not a model's own choice, and
never observe how a real model actually reacts to a genuine rejection
mid-loop. SLOW, requires Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, a fresh database per test. user_alice's
customer_service role has ZERO write: grants of any kind -- writes are
enabled in the loop (write_mediator is passed, so the model's prompt
genuinely offers the capability), but this specific user was never
granted permission to use it.

Deliberately does NOT assert on HOW the model reacts to the denial
(retries, gives up, tries something else) -- that's real, informative
model behavior worth seeing in the diagnostic prints, but not the
actual safety guarantee. The guarantee that must hold regardless of
the model's exact recovery path: the proposal never reaches the
pending stage, and the real database is never touched.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.write_mediator import WriteMediator


@pytest.mark.integration
def test_real_model_write_attempt_is_blocked_without_a_write_grant(deployment, mediator):
    write_mediator = WriteMediator(mediator, deployment.roles)
    loop = AgentLoop.from_deployment(deployment, mediator, write_mediator=write_mediator)
    user_record = resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)

    result = loop.run(user_record, "Update cust_001's name to 'Ada Lovelace'.")

    print(f"\n[diagnostic] pending_write: {result.pending_write}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    # THE actual safety guarantee: no proposal ever reached the pending
    # stage -- WriteMediator.propose_write() correctly raised
    # PermissionError (caught by AgentLoop's own invalid-step recovery)
    # for every attempt, regardless of how many times the model tried
    # or what it tried differently.
    assert result.pending_write is None, (
        f"A user with zero write: grants must never reach the pending "
        f"write stage, but got: {result.pending_write}"
    )

    # And the real database, read back independently of the write path,
    # must be genuinely untouched -- the original seed value.
    real_value = mediator.get_field(user_record, "Customer", "cust_001", "name")
    assert real_value == "Ada Okafor", (
        f"Expected the database to remain at the original seed value, "
        f"but found {real_value!r}"
    )
