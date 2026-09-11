"""
Every step type is declared in THREE places. They must agree.

    AgentLoop._step_handlers()   what the loop can execute
    next_step()                  what the parser will accept
    the system prompt            what the model is told to emit

Nothing asserted that they agreed, and they did not. `aggregate_object`
and `search_around` had handlers and were taught in the prompt, but had
no branch in next_step() -- so an unmatched step fell through to
"unrecognized step {step!r}, finishing" and was silently converted into
a finish. Observed live on a real query:

    unrecognized step 'aggregate_object', finishing

The model had correctly chosen an aggregate for a count question, and
the query ended two steps later having answered by reading a link list.

THE POINT OF THIS FILE IS THE CLASS, NOT THE INSTANCE. Each of the
three sides had its own passing tests. What nobody tested was that they
described the same vocabulary -- which is exactly the kind of bug unit
tests cannot catch, because every side is individually correct.
"""

import re

from core.agent.agentic_loop import AgentLoop
from core.llm.agent_step_prompt import _build_system_prompt, next_step


def _handler_steps() -> set[str]:
    loop = AgentLoop.__new__(AgentLoop)
    return set(loop._step_handlers())


def _parser_accepts(step_name: str) -> bool:
    """Whether next_step() has a real branch for this step type.

    Probed rather than introspected: the branches are inline `if`
    statements, so there is no registry to read. A step type with no
    branch comes back as "finish", which is the failure being guarded.
    """

    class _Says:
        def chat(self, *args, **kwargs):
            # Deliberately minimal -- missing required keys also yield
            # "finish", so a bare step name cannot distinguish "no
            # branch" from "bad step". Probing with a plausible shape
            # per type is what makes the distinction real.
            return _PROBES[step_name]

    return next_step(_Says(), "q", {}, [], [], True, {}).get("step") == step_name


_PROBES = {
    "search_object": '{"step": "search_object", "object_type": "T", "filter": {}}',
    "get_field": '{"step": "get_field", "object_type": "T", "object_id": 1, "field_name": "f"}',
    "get_object": '{"step": "get_object", "object_type": "T", "object_id": 1, "field_names": ["f"]}',
    "aggregate_object": '{"step": "aggregate_object", "object_type": "T", "aggregate": "count"}',
    "search_around": '{"step": "search_around", "object_type": "T", "link_field": "l"}',
    "use_tool": '{"step": "use_tool", "tool_name": "t", "args": {}}',
    "propose_action": '{"step": "propose_action", "action_type": "A", "parameters": {}}',
}


def test_every_handler_has_a_parser_branch():
    # The assertion that would have caught the bug the day it appeared.
    missing = {name for name in _handler_steps() if not _parser_accepts(name)}

    assert not missing, (
        f"these steps have handlers but next_step() silently converts them "
        f"to finish: {sorted(missing)}"
    )


def test_every_probe_covers_a_real_handler():
    # Guards this test file against itself: a probe for a step that no
    # longer exists would quietly stop testing anything.
    assert set(_PROBES) == _handler_steps()


def test_every_step_the_prompt_teaches_has_a_handler():
    # The third side, and the one nobody thinks of. Teaching the model a
    # vocabulary nothing can execute wastes a hop per attempt -- roughly
    # 190 seconds on the CPU-only deployment this was found on.
    prompt = _build_system_prompt({}, [], True, {}, [])
    taught = set(re.findall(r'"step":\s*"([a-z_]+)"', prompt))
    taught.discard("finish")  # handled by the loop, not by a handler

    assert taught <= _handler_steps(), (
        f"the prompt teaches steps with no handler: {sorted(taught - _handler_steps())}"
    )


def test_the_prompt_teaches_every_step_that_has_a_handler():
    # The other direction. A handler nothing is told about is dead code
    # -- it cannot be reached, because only the model emits steps.
    prompt = _build_system_prompt({}, [], True, {}, [])
    taught = set(re.findall(r'"step":\s*"([a-z_]+)"', prompt))

    # use_tool and propose_action are conditional on the deployment
    # having tools or writes enabled, so they are absent from a prompt
    # built without either. Everything else must be taught.
    unconditional = _handler_steps() - {"use_tool", "propose_action"}

    assert unconditional <= taught, (
        f"these handlers exist but the prompt never teaches them: "
        f"{sorted(unconditional - taught)}"
    )


# --- the two steps that were unreachable, exercised properly ---

def test_an_aggregate_step_survives_validation():
    step = _parse('{"step": "aggregate_object", "object_type": "Transaction", '
                  '"aggregate": "count", "filter": {"customer_id": "cust_001"}}')

    assert step["step"] == "aggregate_object"
    assert step["aggregate"] == "count"
    assert step["filter"] == {"customer_id": "cust_001"}


def test_count_needs_no_field_name_but_sum_does():
    # The mediator documents this rule; checking it here saves a whole
    # hop discovering it, which on CPU-only hardware is ~190 seconds.
    assert _parse('{"step": "aggregate_object", "object_type": "T", '
                  '"aggregate": "count"}')["step"] == "aggregate_object"
    assert _parse('{"step": "aggregate_object", "object_type": "T", '
                  '"aggregate": "sum"}')["step"] == "finish"
    assert _parse('{"step": "aggregate_object", "object_type": "T", '
                  '"aggregate": "sum", "field_name": "amount"}')["step"] == "aggregate_object"


def test_an_unknown_aggregate_fails_closed():
    assert _parse('{"step": "aggregate_object", "object_type": "T", '
                  '"aggregate": "median"}')["step"] == "finish"


def test_a_search_around_step_survives_validation():
    step = _parse('{"step": "search_around", "object_type": "Customer", '
                  '"filter": {"name": "Ada"}, "link_field": "transactions"}')

    assert step["step"] == "search_around"
    assert step["link_field"] == "transactions"


def test_filter_defaults_to_empty_rather_than_being_absent():
    # Both handlers call step.get("filter") or {}, so an absent filter
    # is already safe -- but normalising here means the recorded step
    # and the executed step have the same shape, which matters for
    # _step_signature's duplicate detection.
    assert _parse('{"step": "search_around", "object_type": "T", '
                  '"link_field": "l"}')["filter"] == {}
    assert _parse('{"step": "aggregate_object", "object_type": "T", '
                  '"aggregate": "count"}')["filter"] == {}


def _parse(content):
    class _Says:
        def chat(self, *args, **kwargs):
            return content

    return next_step(_Says(), "q", {}, [], [], True, {})
