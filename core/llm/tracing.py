"""
tracing.py  (OpenTelemetry GenAI spans -- optional, and content-free)

AL-7: no standard tracing. A query makes one model call per hop plus
one to synthesise, and the only record of what happened was log lines
and whatever the result object carried.

THE VOCABULARY IS NOT OURS TO INVENT. OpenTelemetry's GenAI semantic
conventions define exactly this shape -- `invoke_agent` for a run,
`chat` for each model call, `execute_tool` for each tool call, with
`gen_ai.*` attributes -- and the alternatives converge on it rather
than compete: OpenInference, OpenLLMetry and OpenLIT all emit
OpenTelemetry spans aligned to these conventions, and OpenLLMetry's
own conventions were upstreamed into OpenTelemetry. The conventions
even name `plan`, which is what AL-4's planner would be.

NO DEPENDENCY IS ADDED, DELIBERATELY. `opentelemetry-sdk` is not in
requirements.txt and this does not put it there -- that is a
LIBRARY_AUDIT decision, not one to smuggle in behind a feature. The
import is optional: without the SDK every span here is a no-op, and
the moment someone installs it the spans appear with no code change.

AND NO INSTRUMENTATION LIBRARY. OpenInference and OpenLLMetry
auto-patch SDK methods at import time to instrument code nobody
wrote. We have one loop and one adapter, both ours, so auto-patching
buys nothing and costs a dependency that rewrites imports. Emitting
three span kinds from the three places that already exist is smaller
and reads in the code. A project that researched this reached the
same conclusion and added the warning that matters: do not introduce
a third telemetry dialect, and do not treat unreleased OTel main as a
stable standard.

THE CONVENTIONS ARE NOT STABLE, and that is why this is behind an
option rather than baked in. As of mid-2026 every `gen_ai.*`
attribute carries the "Development" badge; none is marked Stable, and
there is no published timeline. OpenTelemetry's own answer to that is
an explicit opt-in (`OTEL_SEMCONV_STABILITY_OPT_IN=
gen_ai_latest_experimental`) plus a collector processor that
normalises other dialects into this one, so the churn is absorbed
downstream rather than by us.

WHY IT LIVES UNDER core/llm/ rather than at core/ root, where a
stdlib-only leaf like core/concurrency.py would normally sit: every
span here is a GENAI span. `invoke_agent`, `chat` and `execute_tool`
are the GenAI conventions' own operations, and the module knows what
a model call is. core.agent may import core.llm under the layering
contract, so the three call sites all reach it.

== NO PROMPT OR RESPONSE CONTENT. EVER. ==

The conventions define OPTIONAL content capture -- `gen_ai.input.
messages` and `gen_ai.output.messages` -- carrying the actual prompt
and completion. For this project that option must stay off
permanently, and the reason is not privacy hygiene but the security
model.

Every value a model is shown was released by `check_access()` to a
specific user and written to the audit log as a read by them. A trace
exporter is none of those things: it has no user, applies no MAC or
RBAC, and lands in an observability backend with its own, different,
usually broader access rules. Putting prompt content in a span
creates a SECOND COPY of customer data outside the ontology, which is
exactly what SECURITY_ARCHITECTURE.md means by data reached without
going through the mediator.

So the helpers below accept a fixed set of non-content attributes --
counts, names, model identifiers, durations -- and nothing that can
carry a field value. A test pins it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

# OPTIONAL. No SDK, no spans, no error -- and no dependency in
# requirements.txt to argue about before the feature can exist.
try:  # pragma: no cover - exercised by whether the SDK is installed
    from opentelemetry import trace as _otel_trace

    _TRACER: Any | None = _otel_trace.get_tracer("elysium.agent")
except ImportError:  # pragma: no cover
    _TRACER = None


# The operations this project emits, from the GenAI conventions'
# `gen_ai.operation.name` enum. Named here rather than passed as free
# strings so a typo is a NameError at import rather than a span nobody
# can find.
INVOKE_AGENT = "invoke_agent"
CHAT = "chat"
EXECUTE_TOOL = "execute_tool"

# EVERY ATTRIBUTE THIS MODULE WILL SET. A closed list, because the
# point is not tidiness -- an open one is how `gen_ai.input.messages`
# eventually arrives and puts a customer's field values in a backend
# the ontology does not govern. Adding to this list is a deliberate
# act with a reason beside it.
_PERMITTED_ATTRIBUTES = frozenset({
    "gen_ai.operation.name",
    "gen_ai.agent.name",
    "gen_ai.request.model",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "gen_ai.tool.name",
    # Ours, not the spec's: the stop reason and hop count are the two
    # things a trace is actually consulted for here, and neither can
    # carry a value.
    "elysium.stop_reason",
    "elysium.hops_used",
})


class ContentInSpanError(ValueError):
    """An attribute outside the permitted set was offered to a span.

    Raised rather than dropped. Silently discarding it would leave
    someone believing their attribute was recorded, and the next
    person to add one would not learn why it is a closed list.
    """


def _checked(attributes: dict[str, Any]) -> dict[str, Any]:
    offered = set(attributes)
    if not offered <= _PERMITTED_ATTRIBUTES:
        raise ContentInSpanError(
            f"{sorted(offered - _PERMITTED_ATTRIBUTES)} is not a permitted span "
            f"attribute. Spans carry counts and names, never prompt or "
            f"response content -- see this module's docstring for why."
        )
    return {k: v for k, v in attributes.items() if v is not None}


@contextlib.contextmanager
def span(operation: str, target: str | None = None, **attributes: Any) -> Iterator[None]:
    """One GenAI span, or nothing at all if the SDK is absent.

    THE NAME IS `"{operation} {target}"`, which the conventions
    require -- "Span name SHOULD be invoke_agent {gen_ai.agent.name}
    if gen_ai.agent.name is readily available", and plain
    `{operation}` when it is not.

    ATTRIBUTES ARE CHECKED EVEN WHEN THERE IS NO TRACER, so a
    deployment without the SDK still fails a forbidden attribute at
    the call site rather than discovering it the day tracing is turned
    on.
    """
    checked = _checked({"gen_ai.operation.name": operation, **attributes})
    if _TRACER is None:
        yield
        return
    name = f"{operation} {target}" if target else operation
    with _TRACER.start_as_current_span(name) as active:
        for key, value in checked.items():
            active.set_attribute(key, value)
        yield


def is_enabled() -> bool:
    """Whether spans are actually being emitted.

    For a status endpoint or a test to state the fact rather than
    infer it from whether anything showed up in a backend.
    """
    return _TRACER is not None
