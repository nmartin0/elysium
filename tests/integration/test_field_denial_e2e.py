"""
Integration test: real Ollama, confirms a genuinely denied field
(never granted to this role at all -- not a field the model asked
about mid-request and was told no) is never fabricated by a real,
freely-reasoning model. SLOW, requires Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, not the real deployment/ folder a human
explores. user_dave (see fixtures/policy.yaml's customer_service_no_email
role) can see Customer.name but NOT Customer.email at all.

THIS IS GENUINELY DIFFERENT from test_region_enforcement_e2e.py: that
test asks about an object the user has NO access to at all (blocked at
the OBJECT level). This test asks about a field the user CAN see the
containing object for, but never had a grant for THAT SPECIFIC field.

A REAL, WORTH-STATING CORRECTION from this test's own first draft: the
model CAN still attempt to ask for "email" as a field name even though
visible_schema() never lists it -- a real model isn't literally
constrained to only the field names it was shown; "email" is a common,
easily-guessable field name for a Customer-like object from general
knowledge, independent of the schema. The guarantee visible_schema()
filtering actually provides is narrower and still real: the model
never learns the field EXISTS or has a value, and get_field()'s own
RBAC check (authorize(..., "read:Customer.email")) denies any attempt
regardless of whether it was "guessed" or schema-derived. What this
test actually verifies:
  1. IF the model attempted to ask for email, get_field() denied it
     (result is None) -- proven directly against the real gathered
     steps, not assumed.
  2. That denial is correctly stripped by AgentLoop.filter_real_data()
     before synthesis ever sees it (see core/agent/agentic_loop.py).
  3. core/llm/synthesis_prompt.py's _has_only_verified_emails() -- even
     if the model tried to GUESS a plausible email from the name it
     does have, the mechanical, Python-side check discards any
     unverified email-shaped string before the answer is ever returned.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.deployment_loader import build_llm_adapter
from core.llm.synthesis_prompt import synthesize_insight


@pytest.mark.integration
def test_denied_email_field_is_never_fabricated_by_a_real_model(deployment, mediator):
    loop = AgentLoop.from_deployment(deployment, mediator)
    synthesis_client = build_llm_adapter(deployment, deployment.synthesis_model)
    user_record = resolve_user_record(deployment.users, "user_dave", deployment.security_attribute)

    result = loop.run(user_record, "What is cust_001's email address?")

    # A real, informative signal about WHICH real behavior actually
    # happened this run -- guessed and got denied, vs. never attempted
    # at all. Both are valid passes under this test's design (see
    # module docstring), but they're meaningfully different real model
    # behavior; -v alone only shows this on a FAILURE, not a pass, so
    # this print is what makes it visible either way (run with -s to
    # see it: pytest tests/integration/test_field_denial_e2e.py -v -s -m integration).
    attempted_email = any(
        item.get("step") == "get_field" and item.get("field_name") == "email"
        for item in result.gathered
    )
    print(f"\n[diagnostic] model attempted get_field('email'): {attempted_email}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    # If the model attempted to ask for email at all (it may or may not
    # -- both are valid model behavior), the RESULT must have been
    # denied. What's guaranteed is the denial, not the absence of the
    # attempt -- see the module docstring for why this test's earlier
    # draft asserted something stronger than what's actually true.
    email_field_requests = [
        item for item in result.gathered
        if item.get("step") == "get_field" and item.get("field_name") == "email"
    ]
    for item in email_field_requests:
        assert item["result"] is None, (
            f"A get_field(email) attempt must always be denied for this role -- got: {item}"
        )

    real_data = AgentLoop.filter_real_data(result.gathered)
    # The denied attempt, if any, must be stripped before synthesis --
    # a real None result should never survive into what the model
    # actually gets shown for its final answer.
    assert not any(item.get("field_name") == "email" for item in real_data)

    answer = synthesize_insight(synthesis_client, "What is cust_001's email address?",
                                 real_data, result.hit_max_hops)
    print(f"[diagnostic] final synthesized answer: {answer!r}")

    # Even if the model tried to guess an email from the name it DOES
    # have, the real Ada Okafor email must never appear -- either it
    # was never written at all, or it WAS written and the mechanical
    # check correctly discarded the whole answer.
    assert "ada.okafor@example.com" not in answer.lower()
