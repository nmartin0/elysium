"""
Integration test: real Ollama, confirms hit_max_hops/possibly_incomplete
actually reaches and influences a REAL model's synthesized answer, not
just that our own code correctly sets and threads the flag through
(already proven deterministically in tests/unit/
test_agentic_loop_writes_and_cancellation.py and
tests/unit/test_synthesis_prompt.py). SLOW, requires Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment, not the real deployment/ folder a human
explores.

THE MECHANISM: max_hops is deliberately overridden to 2, far too few
to gather cust_001's full transaction details (amounts AND dates,
across 2 transactions -- normally ~6 real gather steps: search, follow
the transactions link, then 2x amount + 2x date). This makes
hit_max_hops=True a MECHANICAL CERTAINTY regardless of what the real
model decides to do -- not a probabilistic hope that the model happens
to run out of room. Only the model's actual reaction to being told
about it (the answer's wording) is genuinely uncertain, and that part
is checked loosely, not exactly -- see the assertion's own comment.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.deployment_loader import build_llm_adapter
from core.intermediate_layer.auth import resolve_user_record
from core.llm.synthesis_prompt import synthesize_insight


@pytest.mark.integration
def test_max_hops_exhaustion_is_reflected_in_the_real_synthesized_answer(deployment, mediator):
    loop = AgentLoop.from_deployment(deployment, mediator)
    loop.max_hops = 2  # mechanically too few -- see module docstring

    synthesis_client = build_llm_adapter(deployment, deployment.synthesis_model)
    user_record = resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)
    query_text = "What are cust_001's recent transactions, including their amounts and dates?"

    result = loop.run(user_record, query_text)

    # THE mechanical guarantee -- pure Python, not model-dependent.
    assert result.hit_max_hops is True

    real_data = AgentLoop.filter_real_data(result.gathered)
    answer = synthesize_insight(synthesis_client, query_text, real_data, result.hit_max_hops)

    # A model's EXACT wording can't be predicted -- checked loosely,
    # against a reasonable set of indicator phrases the system prompt's
    # own suggested phrasing ("...before the search was stopped...")
    # would plausibly produce, rather than one exact string. If this
    # ever fails, the printed answer lets a human judge directly
    # whether the real miss is "didn't acknowledge incompleteness" or
    # just "phrased it in a way this list didn't anticipate."
    incompleteness_indicators = [
        "stopped", "incomplete", "limited", "not all", "further",
        "additional", "may not", "cut short", "partial", "unable to retrieve",
    ]
    lower_answer = answer.lower()
    assert any(indicator in lower_answer for indicator in incompleteness_indicators), (
        f"Expected the answer to acknowledge the search was cut short, but got: {answer!r}"
    )
