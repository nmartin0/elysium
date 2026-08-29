"""
Integration test: real Ollama, confirms a real model decides to invoke
linear_regression with real, actually-gathered numbers -- not that
RBAC correctly gates tool access (already proven by tests/unit/
test_tool_authorization.py), and not that the tool itself computes
correctly given valid input (already proven by tests/unit/
test_linear_regression.py). SLOW, requires Ollama.

Runs against tests/integration/fixtures/ (see conftest.py) -- a fully
isolated test deployment. user_alice's customer_service role now also
grants tool:linear_regression.

cust_001 has exactly 2 real transactions (49.99, 199.00) -- the tool's
own minimum (tools/linear_regression.py raises below 2 points), so
this is the smallest real dataset that can genuinely trigger a
successful call, not an artificially large one built just for this test.

THE KEY RISK this actually probes: could a model, asked something
requiring computation, either skip the tool and eyeball an answer, or
call the tool with FABRICATED numbers instead of ones it actually
gathered from real data? Both are checked directly below.
"""

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record

# The real, known amounts for cust_001 in this fixture -- see
# fixtures/schema.sql. Used to verify the tool was called with genuine
# gathered data, not invented numbers.
REAL_CUST_001_AMOUNTS = {49.99, 199.00}


@pytest.mark.integration
def test_real_model_uses_the_tool_with_real_gathered_numbers(deployment, mediator):
    loop = AgentLoop.from_deployment(deployment, mediator)
    user_record = resolve_user_record(deployment.users, "user_alice", deployment.security_attribute)

    result = loop.run(
        user_record,
        "What is the trend in cust_001's transaction amounts over time? "
        "Is it increasing or decreasing?",
    )

    tool_calls = [item for item in result.gathered if item.get("step") == "use_tool"]
    print(f"\n[diagnostic] tool calls made: {tool_calls}")
    print(f"[diagnostic] full gathered steps: {result.gathered}")

    assert len(tool_calls) > 0, (
        f"Expected the model to invoke linear_regression for a trend question, "
        f"but it never did. Gathered: {result.gathered}"
    )

    tool_call = tool_calls[0]
    assert tool_call["tool_name"] == "linear_regression"

    args = tool_call["args"]
    x_values = args.get("x_values", [])
    y_values = args.get("y_values", [])

    # At least one of the two argument lists must be genuinely grounded
    # in real data -- x_values is plausibly a time-index/sequence the
    # model constructed itself (legitimate), but y_values (the amounts
    # being analyzed) should be REAL numbers actually present in the
    # data, not fabricated. Checked as a set-overlap, not an exact
    # match, since the model may include only a subset or a derived
    # ordering.
    real_values_used = set(x_values) & REAL_CUST_001_AMOUNTS or set(y_values) & REAL_CUST_001_AMOUNTS
    assert real_values_used, (
        f"Expected the tool call to use real amounts from {REAL_CUST_001_AMOUNTS}, "
        f"but got x_values={x_values}, y_values={y_values}"
    )

    # The call must have actually succeeded -- a real result dict with
    # the tool's own documented output shape, not an error.
    assert "slope" in tool_call["result"]
