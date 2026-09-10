"""
Tests for agent_step_prompt.py's named-action-types additions
(action-types-redesign branch): the model-facing "propose_action"
vocabulary, and the Q4 hybrid design for action visibility -- show an
action normally by default, but annotate it as currently valid/blocked
for a SPECIFIC object once the model has already read enough state
about that object during this same run.

No existing test file covered agent_step_prompt.py directly at all
before this -- it had only ever been exercised indirectly through
real-Ollama integration tests. This file is scoped to what this piece
of work actually built (the new helpers and next_step()'s
propose_action validation), not a retroactive full-module test pass.

ACTION_TYPES uses the sub_writes shape throughout -- the object being
acted on is just an ordinary, object_reference-typed parameter
(ticket_id) now, matching Palantir Foundry's own action parameter
model directly (verified against their docs, not assumed). There is
no longer a separate, model-facing object_id field or step key at all
-- see WriteMediator.propose_action(, origin="human")'s own docstring for the full
reasoning.
"""

from core.llm.agent_step_prompt import (
    _action_state_notes,
    _build_system_prompt,
    _describe_actions,
    _known_state_for_object,
    _sub_write_validity_for_object,
    next_step,
)

ACTION_TYPES = {
    "ReopenTicket": {
        "affected_object_types": ["Ticket"],
        "parameters": {
            "ticket_id": {"type": "object_reference", "object_type": "Ticket", "required": True},
            "reason": {"type": "string", "required": True},
        },
        "sub_writes": [{
            "object_type": "Ticket",
            "object_id": "parameter.ticket_id",
            "operation": "update",
            "submission_criteria": [
                {
                    "description": "Ticket must currently be closed to reopen it",
                    "check": "current_state", "field": "status", "operator": "equals", "value": "closed",
                },
            ],
            "mutations": [
                {"set": {"property": "status", "value": "open"}},
                {"set": {"property": "reopen_reason", "value": "parameter.reason"}},
            ],
        }],
    },
}


def test_known_state_for_object_collects_only_matching_get_field_results():
    gathered = [
        {"step": "get_field", "object_type": "Ticket", "object_id": "t1", "field_name": "status", "result": "closed"},
        {"step": "get_field", "object_type": "Ticket", "object_id": "t2", "field_name": "status", "result": "open"},
        {"step": "get_field", "object_type": "Customer", "object_id": "t1", "field_name": "name", "result": "x"},
        {"step": "search_object", "object_type": "Ticket", "filter": {}, "result": ["t1"]},
    ]
    state = _known_state_for_object(gathered, "Ticket", "t1")
    # Only the ONE matching (type, id) entry -- not t2's, not a
    # different type sharing the same id string, not a search_object.
    assert state == {"status": "closed"}


def test_sub_write_validity_returns_none_when_state_is_incomplete():
    # The sub_write's own criterion needs "status" -- known_state has a
    # DIFFERENT field entirely. Must be None (undeterminable), not a
    # guessed verdict against a missing key.
    sub_write_def = ACTION_TYPES["ReopenTicket"]["sub_writes"][0]
    result = _sub_write_validity_for_object(sub_write_def, {"reopen_reason": None})
    assert result is None


def test_sub_write_validity_true_when_state_satisfies_the_criterion():
    sub_write_def = ACTION_TYPES["ReopenTicket"]["sub_writes"][0]
    result = _sub_write_validity_for_object(sub_write_def, {"status": "closed"})
    assert result == (True, "")


def test_sub_write_validity_false_with_the_real_criterion_description_as_reason():
    sub_write_def = ACTION_TYPES["ReopenTicket"]["sub_writes"][0]
    is_valid, reason = _sub_write_validity_for_object(sub_write_def, {"status": "open"})
    assert is_valid is False
    assert reason == "Ticket must currently be closed to reopen it"


def test_describe_actions_shows_no_verdict_with_no_known_state():
    # The catalogue is now STATIC -- it never carried verdicts. Kept
    # pointed at _describe_actions deliberately: this asserts the
    # static block stays clean, which is what makes it cacheable.
    text = _describe_actions(ACTION_TYPES)
    assert "ReopenTicket" in text
    assert "propose_action" in text
    assert "Currently valid" not in text
    assert "Currently blocked" not in text


def test_describe_actions_annotates_a_known_valid_object():
    # The hint is now keyed by the PARAMETER name (ticket_id), not a
    # bare "Currently valid for: ..." -- necessary once an action can
    # have more than one object_reference parameter, each needing its
    # own, independently-computed hint (see _object_reference_hints()'s
    # own docstring).
    gathered = [
        {"step": "get_field", "object_type": "Ticket", "object_id": "t1", "field_name": "status", "result": "closed"}
    ]
    text = _action_state_notes(ACTION_TYPES, gathered)
    assert "Currently valid for ticket_id: t1" in text


def test_describe_actions_annotates_a_known_blocked_object_with_reason():
    gathered = [
        {"step": "get_field", "object_type": "Ticket", "object_id": "t2", "field_name": "status", "result": "open"}
    ]
    text = _action_state_notes(ACTION_TYPES, gathered)
    assert "Currently blocked for ticket_id: t2 (Ticket must currently be closed to reopen it)" in text


def test_describe_actions_handles_multiple_known_objects_independently():
    gathered = [
        {"step": "get_field", "object_type": "Ticket", "object_id": "t1", "field_name": "status", "result": "closed"},
        {"step": "get_field", "object_type": "Ticket", "object_id": "t2", "field_name": "status", "result": "open"},
    ]
    text = _action_state_notes(ACTION_TYPES, gathered)
    assert "Currently valid for ticket_id: t1" in text
    assert "Currently blocked for ticket_id: t2 (Ticket must currently be closed to reopen it)" in text


def test_system_prompt_includes_actions_section_when_visible_and_writes_enabled():
    prompt = _build_system_prompt({}, [], True, ACTION_TYPES, [])
    assert "propose_action" in prompt
    assert "ReopenTicket" in prompt


def test_system_prompt_omits_actions_section_when_no_actions_are_visible():
    # Empty visible_action_types -- e.g. this user has zero execute:
    # grants. Must produce ZERO mention of propose_action, not an
    # empty/confusing section.
    prompt = _build_system_prompt({}, [], True, {}, [])
    assert "propose_action" not in prompt


def test_system_prompt_omits_actions_section_when_writes_disabled_even_with_visible_actions():
    # writes_enabled=False must suppress the ENTIRE actions section,
    # regardless of what visible_action_types contains.
    prompt = _build_system_prompt({}, [], False, ACTION_TYPES, [])
    assert "propose_action" not in prompt


class _FakeClient:
    def __init__(self, response: str):
        self._response = response

    def chat(self, *args, **kwargs):
        return self._response


def test_next_step_accepts_a_well_formed_propose_action_step():
    # No separate "object_id" field at all -- ticket_id is just
    # another entry in "parameters", the same as "reason" is.
    client = _FakeClient(
        '{"step": "propose_action", "action_type": "ReopenTicket", '
        '"parameters": {"ticket_id": "t1", "reason": "x"}}'
    )
    step = next_step(client, "reopen it", {}, [], [], True, ACTION_TYPES)
    assert step == {
        "step": "propose_action", "action_type": "ReopenTicket",
        "parameters": {"ticket_id": "t1", "reason": "x"},
    }


def test_next_step_fails_closed_on_malformed_propose_action_step():
    # Missing "parameters" entirely -- must fail closed to finish, not
    # crash or pass through a malformed step.
    client = _FakeClient('{"step": "propose_action", "action_type": "ReopenTicket"}')
    step = next_step(client, "reopen it", {}, [], [], True, ACTION_TYPES)
    assert step == {"step": "finish"}


# --- prompt stability across hops ---
#
# WHY THIS IS ASSERTED. The step prompt is re-sent every hop, and an
# LLM server reuses the computed attention state of a shared PREFIX.
# When the per-object action verdicts lived inside _describe_actions()
# they changed the MIDDLE of the system prompt on the exact hop a
# write became relevant, invalidating that prefix.
#
# Measured on the CPU-only deployment before this split, one query:
#
#   call 1: 298.0s   (cold)
#   call 2:  30.7s   (prefix reused)
#   call 3:  32.3s   (prefix reused)
#   call 4: 192.8s   <- first Transaction entered gathered
#   call 5: 192.5s   <- second Transaction entered gathered
#
# 322 seconds of a 746-second query, spent re-reading a prompt that
# changed only because an annotation moved.

_STABLE_PREFIX_END = "Current action availability"


def _prompt(gathered):
    return _build_system_prompt({}, [], True, ACTION_TYPES, gathered)


def test_the_system_prompt_prefix_is_identical_regardless_of_gathered():
    # THE PROPERTY THAT MATTERS. Everything up to the trailing notes
    # must be byte-identical, or the cached prefix is thrown away.
    empty = _prompt([])
    with_state = _prompt([
        {"step": "get_field", "object_type": "Ticket", "object_id": "t1",
         "field_name": "status", "result": "closed"},
    ])

    assert with_state != empty, "the notes must actually appear, or this proves nothing"
    prefix = empty.split(_STABLE_PREFIX_END)[0]
    assert with_state.startswith(prefix)


def test_the_verdicts_still_reach_the_prompt():
    # The control for the test above: a prompt that never annotated
    # anything would trivially have a stable prefix and be useless.
    text = _prompt([
        {"step": "get_field", "object_type": "Ticket", "object_id": "t1",
         "field_name": "status", "result": "closed"},
    ])

    assert "Currently valid for ticket_id: t1" in text


def test_the_notes_section_is_absent_entirely_when_nothing_is_known():
    # An empty section is worse than no section -- the same gating
    # discipline the tools and writes sections already use.
    assert _STABLE_PREFIX_END not in _prompt([])


def test_the_verdicts_come_after_every_instruction():
    # Position, not just presence. Appended LAST, matching
    # core/llm/synthesis_prompt.py's own SYSTEM_PROMPT + note pattern.
    text = _prompt([
        {"step": "get_field", "object_type": "Ticket", "object_id": "t1",
         "field_name": "status", "result": "closed"},
    ])

    assert text.index(_STABLE_PREFIX_END) > text.index("IMPORTANT")
