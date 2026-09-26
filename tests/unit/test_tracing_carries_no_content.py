"""Spans carry counts and names. Never a field value.

AL-7: no standard tracing. The vocabulary is OpenTelemetry's GenAI
semantic conventions -- `invoke_agent`, `chat`, `execute_tool` -- and
the alternatives converge on it rather than compete with it.

MOST OF THIS FILE IS ABOUT WHAT A SPAN MUST NOT CARRY.

The conventions define OPTIONAL content capture,
`gen_ai.input.messages` and `gen_ai.output.messages`, holding the
actual prompt and completion. For this project that option must stay
off permanently, and not for privacy hygiene.

Every value a model is shown was released by `check_access()` to a
named user and written to the audit log as a read by them. A trace
exporter is none of those things: no user, no MAC, no RBAC, and it
lands in a backend with its own and usually broader access rules. A
prompt in a span is a second copy of customer data outside the
ontology -- data reached without going through the mediator, which is
the one thing SECURITY_ARCHITECTURE.md does not allow.

So the permitted attributes are a closed list and this asserts it.
"""

import pytest

from core.llm.tracing import (
    CHAT,
    EXECUTE_TOOL,
    INVOKE_AGENT,
    ContentInSpanError,
    is_enabled,
    span,
)

# ------------------------------------------------------ what cannot get in


@pytest.mark.parametrize("forbidden", [
    "gen_ai.input.messages",
    "gen_ai.output.messages",
    "gen_ai.prompt",
    "gen_ai.completion",
    "elysium.gathered",
    "elysium.query_text",
    "gen_ai.tool.call.arguments",
])
def test_content_attributes_are_refused(forbidden):
    """THE POINT OF THE MODULE.

    Each of these is a real attribute name from the conventions or an
    obvious thing someone would reach for, and every one of them
    carries a field value the ontology released to one user.
    """
    with pytest.raises(ContentInSpanError):
        with span(CHAT, "step", **{forbidden: "Ada Okafor"}):
            pass


def test_a_forbidden_attribute_is_refused_even_with_no_tracer():
    """CHECKED WHETHER OR NOT SPANS ARE BEING EMITTED.

    Otherwise a deployment without the SDK would accept a forbidden
    attribute silently and discover it the day tracing is switched on
    -- which is the day the data starts leaving.
    """
    with pytest.raises(ContentInSpanError):
        with span(INVOKE_AGENT, "elysium", **{"gen_ai.prompt": "x"}):
            pass


def test_the_refusal_names_what_was_wrong():
    """Raised rather than dropped: silently discarding leaves someone
    believing their attribute was recorded."""
    with pytest.raises(ContentInSpanError, match="gen_ai.prompt"):
        with span(CHAT, "step", **{"gen_ai.prompt": "x"}):
            pass


# --------------------------------------------------------- what can get in


@pytest.mark.parametrize(("attribute", "value"), [
    ("gen_ai.request.model", "phi4-mini"),
    ("gen_ai.usage.input_tokens", 1234),
    ("gen_ai.usage.output_tokens", 56),
    ("gen_ai.tool.name", "calculator"),
    ("elysium.stop_reason", "finished"),
    ("elysium.hops_used", 7),
])
def test_counts_and_names_are_permitted(attribute, value):
    """None of these can carry a field value: a model name, a token
    count, a tool name, a stop reason, a hop count."""
    with span(CHAT, "step", **{attribute: value}):
        pass


def test_the_three_operations_the_conventions_name():
    """`invoke_agent` for the run, `chat` for each model call,
    `execute_tool` for each tool call -- the span tree the GenAI
    conventions define, and what any OTel backend expects."""
    assert INVOKE_AGENT == "invoke_agent"
    assert CHAT == "chat"
    assert EXECUTE_TOOL == "execute_tool"


# ------------------------------------------------------------- no dependency


def test_it_works_with_or_without_the_sdk():
    """`opentelemetry-sdk` is NOT in requirements.txt and this does not
    put it there -- that is a LIBRARY_AUDIT decision, not one to
    smuggle in behind a feature. Without the SDK every span is a
    no-op; with it they appear, no code change."""
    assert isinstance(is_enabled(), bool)

    with span(INVOKE_AGENT, "elysium"):
        pass  # must not raise either way


def test_a_span_does_not_swallow_an_exception():
    """A context manager around the loop must not turn a failure into
    a success. If it did, tracing would be a correctness change."""
    with pytest.raises(ZeroDivisionError):
        with span(INVOKE_AGENT, "elysium"):
            raise ZeroDivisionError("from inside the span")


def test_a_span_returns_what_the_body_produced():
    """It wraps, it does not intercept."""
    result = []
    with span(EXECUTE_TOOL, "calculator", **{"gen_ai.tool.name": "calculator"}):
        result.append(42)

    assert result == [42]
