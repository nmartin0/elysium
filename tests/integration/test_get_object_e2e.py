"""
Integration test: real Ollama, confirms a REAL model actually chooses
get_object -- not just that the mechanism works when scripted (already
proven, thoroughly, by tests/unit/test_mediator.py, tests/unit/
test_agent_step_prompt.py, and tests/unit/test_agentic_loop_get_
object.py). This is the first time a real model's own reasoning ever
sees the get_object vocabulary at all.

QUERY_TEXT asks for TWO fields of the SAME object explicitly, up
front, in one sentence -- giving the model every reasonable chance to
recognize this is exactly the case core/llm/agent_step_prompt.py's own
system prompt describes get_object as the PREFERRED choice for
("whenever you already know you need more than one field from the
same object"), not a contrived or ambiguous case.

Observed via a direct spy on DataMediator.get_object() itself (was it
called at all during this real run()), NOT by trying to infer the
choice from the final `gathered` list -- core/agent/agentic_loop.py's
own get_object handling deliberately expands its result into
get_field-shaped gathered[] entries (see that file's own AI-notes for
why), so gathered alone can never distinguish "the model used
get_object" from "the model used two separate get_field calls that
happened to return the same two fields." Spying on the real method
call is the only reliable way to observe which path a real model
actually took.

Runs against tests/integration/fixtures/ (see conftest.py). user_alice
(customer_service role) already has both read:Customer.name and
read:Customer.email -- no new grant needed. SLOW, requires Ollama.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record

QUERY_TEXT = "What are cust_001's name and email?"


@pytest.mark.integration
def test_real_model_uses_get_object_for_a_genuine_multi_field_lookup(deployment, mediator, monkeypatch):
    calls = []
    original_get_object = mediator.get_object

    def spy_get_object(*args, **kwargs):
        calls.append((args, kwargs))
        return original_get_object(*args, **kwargs)

    monkeypatch.setattr(mediator, "get_object", spy_get_object)

    loop = AgentLoop.from_deployment(deployment, mediator)
    user_record = resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)
    result = loop.run(user_record, QUERY_TEXT)
    print(f"\n[diagnostic] gathered: {result.gathered}")
    print(f"[diagnostic] get_object call count: {len(calls)}")

    assert len(calls) >= 1, (
        f"Expected the model to choose get_object at least once for a query "
        f"explicitly asking for two fields of the same object, but it never did. "
        f"gathered={result.gathered}"
    )

    # Regardless of exactly how many get_object/get_field calls the
    # model made, the FINAL gathered state must correctly contain both
    # real values -- the real, seeded data, not a hardcoded expectation
    # about which step produced it.
    get_field_entries = {
        item["field_name"]: item["result"] for item in result.gathered if item.get("step") == "get_field"
    }
    assert get_field_entries.get("name") == "Ada Okafor", (
        f"Expected the real seeded name 'Ada Okafor', got {get_field_entries.get('name')!r}. "
        f"gathered={result.gathered}"
    )
    assert get_field_entries.get("email") == "ada.okafor@example.com", (
        f"Expected the real seeded email, got {get_field_entries.get('email')!r}. "
        f"gathered={result.gathered}"
    )


# =============================================================================
# AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
# later) that lacks this conversation's history. Update this section whenever
# something genuinely open, deferred, or rejected comes up for this file.
# =============================================================================
#
# IMPORTANT CAVEAT: built and verified as thoroughly as possible
# WITHOUT a real Ollama server -- none was available in the
# environment this was written in. Verified directly: the test
# collects correctly, and fails FAST and CLEANLY (not a hang, not a
# confusing traceback) with the exact same "Connection refused"
# signature test_transfer_funds_e2e.py's own notes already document,
# when Ollama is genuinely unreachable -- safe to leave for a human to
# run for real. What was NOT verified: whether a real model actually
# prefers get_object over two separate get_field calls for this
# query. That is this whole file's actual point, and remains
# genuinely open until run for real. If a real model does NOT choose
# get_object reliably, consider whether the prompt's own get_object
# section (core/llm/agent_step_prompt.py's _build_system_prompt(),
# the "prefer this over several separate get_field calls" language)
# needs to be more insistent before assuming the mechanism itself has
# a bug -- the mechanism's own correctness, independent of any
# model's own preference, is already separately and thoroughly proven
# by tests/unit/test_agentic_loop_get_object.py.
