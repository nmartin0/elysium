"""
The agent trace harness: run one query, show what the agent did.

Exists because the integration suite is all-or-nothing -- seventeen
scenarios took 1h35m on a local model -- and a failure gave a pytest
traceback rather than the agent's own steps. `gathered` was printed as
one long dict, which is where the answer usually is and the hardest
place to read it.

Tested for the RENDERING and the failure path, not for what a model
does with a query. It asserts nothing about agent behaviour on
purpose: the thing you use it to find out is what the agent chose, and
a harness with an expected output would only tell you whether it
matched something already predicted.
"""

import json

from scripts.agent_trace import _LOOP_NOTES, _render


def test_a_step_shows_its_arguments_and_its_result():
    line = _render(
        {"step": "search_object", "object_type": "Customer",
         "filter": {"name": "Ada"}, "result": ["cust_001"]},
        1,
    )

    assert "search_object" in line
    assert "Customer" in line
    assert "1 item(s)" in line
    assert "cust_001" in line


def test_the_result_is_not_repeated_inside_the_arguments():
    # The arguments line is meant to be readable at a glance; a
    # thousand ids inlined into it defeats that.
    line = _render(
        {"step": "search_object", "object_type": "Customer",
         "filter": {}, "result": [f"c{i}" for i in range(1000)]},
        1,
    )

    arguments, _, preview = line.partition("\n")
    assert "c500" not in arguments
    assert "1000 item(s)" in preview


def test_a_long_result_is_truncated():
    line = _render(
        {"step": "get_object", "object_type": "Customer", "object_id": "c1",
         "result": {f"field{i}": "x" * 40 for i in range(20)}},
        1,
    )

    for rendered in line.split("\n"):
        assert len(rendered) <= 170


def test_loop_notes_render_differently_from_gathered_data():
    # A run full of rejected steps is a different problem from a run
    # that gathered the wrong things, and the trace should not make
    # them look alike.
    note = _render({"step": "rejected_duplicate", "note": "asked twice"}, 3)
    data = _render({"step": "get_field", "object_type": "C", "result": "v"}, 4)

    assert "[rejected_duplicate]" in note
    assert "asked twice" in note
    assert "[" not in data.split("\n")[0].split(".", 1)[1]


def test_every_loop_note_the_loop_can_emit_is_recognised():
    # If the loop gains a new self-note, the trace should not render it
    # as though it were gathered data.
    import inspect

    from core.agent import agentic_loop

    source = inspect.getsource(agentic_loop)
    emitted = {
        line.split('"')[1]
        for line in source.split("\n")
        if 'rejected_step_name="' in line
    }
    emitted.add("completeness_check")

    assert emitted <= _LOOP_NOTES, (
        f"the loop emits notes the trace does not know about: {sorted(emitted - _LOOP_NOTES)}"
    )


def test_a_result_that_is_not_a_collection_still_renders():
    assert "None" in _render({"step": "get_field", "result": None}, 1)
    assert "42" in _render({"step": "get_field", "result": 42}, 1)


def test_arguments_survive_a_json_unfriendly_value():
    # Real gathered steps carry ids that may not be JSON scalars --
    # a date, a Decimal. The trace must render, not raise.
    import datetime

    line = _render(
        {"step": "get_field", "object_type": "T",
         "object_id": datetime.date(2024, 1, 1), "result": "v"},
        1,
    )

    assert "2024-01-01" in line
    assert json.dumps  # the renderer uses default=str rather than failing
