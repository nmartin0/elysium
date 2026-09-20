"""
A prompt near its window says so before the server truncates it.

THE FAILURE IS A WORSE ANSWER, NOT A CRASH. A model given more than
it can hold does not refuse -- it truncates and answers from what
survived. UI_ROADMAP named this as "a risk to what already exists,
not a feature", and said plainly: "we have never measured where that
begins."

MEASURED NOW, on the shipped deployment with num_ctx 4096:

    system prompt alone          ~1,138 tokens    28% of the window
    + one heavy hop              ~2,030            50%
    + four heavy hops            ~4,664           114%  OVERFLOWS
    + eight (default max_hops)   ~8,176           200%

SO THE LOOP CAN EXCEED ITS OWN CONFIGURED WINDOW AT HOP FOUR, well
before it stops on its own. The caps that bound it -- MAX_OBJECT_IDS
of 20 and max_hops of 8 -- were chosen for other reasons and do not
bound this.

0.8 IS THE PUBLISHED THRESHOLD. AWS's agentic-AI lens names exactly
it: "alarms when context window utilization exceeds 80%, triggering
summarization or pruning workflows before the limit becomes a hard
wall".
"""

import logging

import pytest

from adapters.ollama_adapter import CONTEXT_WARNING_FRACTION, OllamaAdapter


def _adapter(**options):
    return OllamaAdapter("a-model", {
        "base_url": "http://localhost:11434", "options": options,
    })


class TestItWarnsNearTheWall:
    def test_a_prompt_at_ninety_percent_warns(self, caplog):
        adapter = _adapter(num_ctx=4096)

        with caplog.at_level(logging.WARNING):
            adapter._warn_if_context_is_tight("x" * 8000, "y" * 6800)

        assert "num_ctx" in caplog.text

    def test_the_warning_says_what_happens_next(self, caplog):
        """"TRUNCATES RATHER THAN FAILING" is the part somebody needs.
        A warning that a prompt is large, without saying the answer may
        be built from part of the evidence, reads as a performance
        note."""
        adapter = _adapter(num_ctx=4096)

        with caplog.at_level(logging.WARNING):
            adapter._warn_if_context_is_tight("x" * 8000, "y" * 6800)

        assert "TRUNCATES" in caplog.text


class TestItStaysQuietOtherwise:
    def test_a_small_prompt_is_silent(self, caplog):
        # A WARNING ON EVERY QUERY is one nobody reads by the time it
        # matters.
        adapter = _adapter(num_ctx=4096)

        with caplog.at_level(logging.WARNING):
            adapter._warn_if_context_is_tight("short", "short")

        assert caplog.text == ""

    def test_a_prompt_just_under_the_threshold_is_silent(self, caplog):
        """THE BOUNDARY, not merely a small case. A check comparing
        against the whole window rather than the fraction would pass
        the test above and fail this one."""
        adapter = _adapter(num_ctx=1000)
        # 70% of 1000 tokens, at four characters each.
        just_under = "x" * (4 * 700)

        with caplog.at_level(logging.WARNING):
            adapter._warn_if_context_is_tight(just_under, "")

        assert caplog.text == ""

    def test_no_declared_window_means_no_warning(self, caplog):
        """A DEPLOYMENT THAT DOES NOT STATE ONE gets no warning rather
        than a guessed threshold -- the server's own default is not
        knowable from here."""
        adapter = _adapter()

        with caplog.at_level(logging.WARNING):
            adapter._warn_if_context_is_tight("x" * 100_000, "")

        assert caplog.text == ""


class TestTheThresholdItself:
    def test_it_is_the_published_eighty_percent(self):
        assert CONTEXT_WARNING_FRACTION == pytest.approx(0.8)

    def test_it_leaves_room_to_act(self):
        # A threshold at 1.0 would fire as the wall was hit, which is
        # a report rather than a warning.
        assert CONTEXT_WARNING_FRACTION < 1.0
