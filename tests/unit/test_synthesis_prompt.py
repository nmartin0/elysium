"""
Tests for synthesis_prompt.py's citation-verification logic --
_has_only_valid_citations() and synthesize_insight()'s fail-closed
behavior when a citation references a record that doesn't exist.

Deliberately does NOT test "does the model actually cite things
correctly" -- that requires a real model (see tests/integration/
test_full_roundtrip.py). This tests the PYTHON-side verification
mechanism itself, given a scripted answer, the same way the rest of
tests/unit/ tests mechanisms in isolation from model behavior.
"""

from core.llm.synthesis_prompt import _has_only_valid_citations, synthesize_insight


class _FakeClient:
    """A minimal LLMAdapter -- returns a scripted answer regardless of input."""
    max_concurrent_requests = None

    def __init__(self, scripted_answer: str):
        self.scripted_answer = scripted_answer

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None):
        return self.scripted_answer


# --- _has_only_valid_citations() -- the pure verification logic itself

def test_valid_citations_within_range():
    assert _has_only_valid_citations("Alice works in [R1] engineering, per [R2].", record_count=2) is True


def test_citation_to_nonexistent_record_is_invalid():
    assert _has_only_valid_citations("Per [R5], Alice works in engineering.", record_count=3) is False


def test_mixed_valid_and_invalid_citations_is_invalid():
    # ANY invalid citation fails the whole check -- fail closed, not
    # "salvage the valid parts."
    assert _has_only_valid_citations("[R1] and also [R5] say so.", record_count=3) is False


def test_zero_citations_is_vacuously_valid():
    # Deliberate scope limitation -- see module docstring. An uncited
    # answer isn't flagged by THIS check; that's a genuinely different,
    # not-mechanically-checkable risk.
    assert _has_only_valid_citations("Alice works in engineering.", record_count=3) is True


def test_citation_r0_is_invalid_records_are_one_indexed():
    assert _has_only_valid_citations("Per [R0], ...", record_count=5) is False


def test_citation_at_exact_upper_boundary_is_valid():
    assert _has_only_valid_citations("Per [R3].", record_count=3) is True


def test_citation_one_past_upper_boundary_is_invalid():
    assert _has_only_valid_citations("Per [R4].", record_count=3) is False


# --- synthesize_insight()'s end-to-end fail-closed behavior

def test_synthesize_insight_passes_through_a_validly_cited_answer():
    client = _FakeClient("Alice's department is engineering [R1].")
    answer = synthesize_insight(client, "What is Alice's department?", [{"department": "engineering"}])
    assert answer == "Alice's department is engineering [R1]."


def test_synthesize_insight_discards_an_answer_with_a_fabricated_citation():
    # The model cites [R2], but only ONE record was ever actually
    # provided -- exactly the scenario this whole mechanism exists to
    # catch: the model referencing something it was never given.
    client = _FakeClient("Alice's email is alice@example.com [R2].")
    answer = synthesize_insight(client, "What is Alice's email?", [{"department": "engineering"}])
    assert "alice@example.com" not in answer
    assert "could not be verified" in answer


def test_synthesize_insight_passes_through_an_uncited_answer_unchanged():
    # Matches the deliberate scope limitation -- not claiming to catch
    # this case, just confirming it doesn't accidentally get swept up.
    client = _FakeClient("Alice works in engineering.")
    answer = synthesize_insight(client, "What is Alice's department?", [{"department": "engineering"}])
    assert answer == "Alice works in engineering."


def test_synthesize_insight_still_short_circuits_on_empty_records():
    # Pre-existing behavior, unaffected by the citation check -- the
    # model is never even called when there's nothing to synthesize.
    client = _FakeClient("this should never be returned")
    answer = synthesize_insight(client, "What is Alice's department?", [])
    assert "no matching records were found" in answer


def test_possibly_incomplete_appends_the_note_to_the_system_prompt():
    # Captures what was ACTUALLY sent to the model, not just the
    # returned answer -- proves the note genuinely reaches the prompt,
    # not just that the function accepts the parameter without erroring.
    captured = {}

    class _CapturingClient:
        max_concurrent_requests = None

        def chat(self, system_prompt, user_message, json_mode=False, temperature=None):
            captured["system_prompt"] = system_prompt
            return "Ada works in engineering [R1]."

    synthesize_insight(_CapturingClient(), "test", [{"department": "engineering"}], possibly_incomplete=True)
    assert "stopped before it could necessarily finish" in captured["system_prompt"]


def test_possibly_incomplete_false_leaves_the_system_prompt_unchanged():
    captured = {}

    class _CapturingClient:
        max_concurrent_requests = None

        def chat(self, system_prompt, user_message, json_mode=False, temperature=None):
            captured["system_prompt"] = system_prompt
            return "Ada works in engineering [R1]."

    synthesize_insight(_CapturingClient(), "test", [{"department": "engineering"}], possibly_incomplete=False)
    assert "stopped before it could necessarily finish" not in captured["system_prompt"]


def test_possibly_incomplete_default_matches_false():
    # The parameter is optional -- every existing caller not yet
    # updated to pass it must keep behaving exactly as before.
    captured = {}

    class _CapturingClient:
        max_concurrent_requests = None

        def chat(self, system_prompt, user_message, json_mode=False, temperature=None):
            captured["system_prompt"] = system_prompt
            return "Ada works in engineering [R1]."

    synthesize_insight(_CapturingClient(), "test", [{"department": "engineering"}])
    assert "stopped before it could necessarily finish" not in captured["system_prompt"]


def test_synthesize_insight_never_mutates_the_shared_system_prompt_constant():
    # A real, worth-guarding-against bug class: appending to SYSTEM_PROMPT
    # itself (rather than building a local string) would leak the
    # incomplete-search note into EVERY subsequent call, including ones
    # that never asked for it.
    from core.llm.synthesis_prompt import SYSTEM_PROMPT
    original = SYSTEM_PROMPT

    client = _FakeClient("Ada works in engineering [R1].")
    synthesize_insight(client, "test", [{"department": "engineering"}], possibly_incomplete=True)

    from core.llm.synthesis_prompt import SYSTEM_PROMPT as system_prompt_after
    assert system_prompt_after == original
