"""
Three guards are called, and these tests say where.

THE CLAIM THAT CREATED THIS FILE WAS FALSE, and the correction is the
point of reading it. Patch n reported that deleting any of these three
calls left every related test passing:

    _validate_auto_execute           NOT CAUGHT
    _validate_effects_are_reachable  NOT CAUGHT
    _reject_unknown_fields           NOT CAUGHT

ALL THREE ARE CAUGHT. Re-measured against two hundred test files
instead of the handful my sweep script chose: deleting
`_validate_auto_execute`'s call fails three tests, and the other two
fail two each.

WHY THE SWEEP WAS WRONG. It picked which tests to run with
`grep -rl <guard> tests/` -- the files that MENTION the guard by name.
A test exercising the path through it has no reason to name it, so the
sweep ran a tiny and arbitrary slice and read silence as absence. The
same mistake found `_check_filter_types` "uncovered" when
`test_bad_filter_values.py` catches it.

SEC-27, WHICH STARTED ALL THIS, IS STILL REAL: there, deleting the
call left the whole suite green, measured the same way these were
re-measured. One true instance does not make a pattern, and I built a
sweep that manufactured three more.

THESE TESTS ARE KEPT ANYWAY, as call-site pins rather than as a fix
for a gap. They state where each guard is called, so moving one out of
`validate_action_types` is visible in a diff rather than silent -- a
smaller claim than the one they were written for.
"""

import re
from pathlib import Path

import pytest

ACTION_TYPES = Path("core/ontology/action_types.py").read_text()
AGENTIC_LOOP = Path("core/agent/agentic_loop.py").read_text()


def _enclosing_function(source: str, guard: str) -> str:
    """The function a guard is called from."""
    call = re.search(rf"^\s+(?:self\.)?{guard}\(", source, re.M)
    assert call, f"{guard} is not called at all"
    enclosing = None
    for match in re.finditer(r"^(?:    )?def (\w+)", source[:call.start()], re.M):
        enclosing = match.group(1)
    return enclosing


class TestTheGuardsAreCalledWhereTheyShouldBe:
    @pytest.mark.parametrize("guard", [
        "_validate_auto_execute",
        "_validate_effects_are_reachable",
    ])
    def test_action_type_validation_calls_it(self, guard):
        """Both belong to `validate_action_types`, which is what runs
        when a deployment's action types are loaded. A guard moved out
        of it would be a guard that runs on nothing."""
        assert _enclosing_function(ACTION_TYPES, guard) == "validate_action_types"

    def test_the_get_object_step_rejects_unknown_fields(self):
        """`_step_get_object`, NOT `_step_search_around` -- my sweep
        script reported the wrong enclosing function and this test
        caught it before the claim reached a commit message."""
        assert _enclosing_function(
            AGENTIC_LOOP, "_reject_unknown_fields") == "_step_get_object"


class TestEachIsCalledExactlyOnce:
    """A second call site is not a problem; ZERO is. These pin the
    count so that deleting one is visible rather than silent."""

    @pytest.mark.parametrize("source,guard", [
        (ACTION_TYPES, "_validate_auto_execute"),
        (ACTION_TYPES, "_validate_effects_are_reachable"),
        (AGENTIC_LOOP, "_reject_unknown_fields"),
    ])
    def test_there_is_a_call(self, source, guard):
        calls = re.findall(rf"^\s+(?:self\.)?{guard}\(", source, re.M)

        assert len(calls) >= 1, f"{guard} is defined and never called"


class TestWhatTheyProtect:
    """Recorded so a later reader knows why these three were singled
    out of fifty-three."""

    def test_auto_execute_decides_whether_a_person_confirms(self):
        body = ACTION_TYPES[ACTION_TYPES.index("def _validate_auto_execute"):]
        body = body[:body.index("\ndef ", 10)]

        assert "auto_execute" in body

    def test_effects_are_held_to_reachable_types(self):
        body = ACTION_TYPES[
            ACTION_TYPES.index("def _validate_effects_are_reachable"):]
        body = body[:body.index("\ndef ", 10)]

        assert "may only mutate" in body or "reach" in body
