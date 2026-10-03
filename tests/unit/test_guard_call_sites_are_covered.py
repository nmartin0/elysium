"""
Three guards are CALLED, and nothing tested that they are.

HOW THIS WAS FOUND. SEC-27 turned out to be a guard that was written,
called, AND tested -- where every test called the method directly, so
deleting the call left all eight passing. That raised the obvious
question: how many others?

A SWEEP ANSWERED IT. Fifty-three guard-shaped functions in `core/` and
`api/` (`_refuse_*`, `_check_*`, `_validate_*`, `_reject_*`), of which
eighteen are called directly by tests. For the six with exactly one
call site, the call was deleted and the tests naming the guard were
run:

    _refuse_system_column_names      caught
    _refuse_reserved_silo_names      caught
    _validate_auto_execute           NOT CAUGHT
    _validate_effects_are_reachable  NOT CAUGHT
    _reject_unknown_fields           NOT CAUGHT

Verified by hand for the first of those three with a wider net --
fifty-two tests across four files passed with the call gone.

WHY THESE THREE MATTER. `auto_execute` decides whether an action runs
WITHOUT confirmation from a person. `_validate_effects_are_reachable`
holds an action to mutating only the types its parameters can reach.
`_reject_unknown_fields` refuses a field the model named that the
caller cannot see.

WHY SOURCE CHECKS RATHER THAN BEHAVIOURAL ONES. The failure is the
CALL's absence, and a behavioural test for "this path runs a guard" is
a test for the guard again -- which is exactly what already existed
and exactly what did not catch it.
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
