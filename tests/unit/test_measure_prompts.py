"""
What the measurement harness counts.

WHY TESTS FOR A SCRIPT NOBODY RUNS IN CI: the harness cannot be run
where it was written -- there is no model here -- so every line of it
is a claim until a person runs it against one. These tests pin the
COUNTING, which is the part that would silently produce a plausible
wrong number.

A harness that miscounts hops does not fail. It reports a median and a
range, and someone changes a prompt on the strength of it.
"""

import pytest

from core.llm.interface import LLMUnavailable
from scripts.measure_prompts import Observation, _summarise, observe


class _Result:
    def __init__(self, gathered, hit_max_hops=False, cancelled=False):
        self.gathered = gathered
        self.hit_max_hops = hit_max_hops
        self.cancelled = cancelled


class _Loop:
    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises

    def run(self, user_record, query_text):
        if self._raises is not None:
            raise self._raises
        return self._result


class TestCounting:
    def test_hops_are_every_gathered_step(self):
        loop = _Loop(_Result([
            {"step": "get_object", "object_type": "Customer", "object_id": "1"},
            {"step": "get_field", "object_type": "Customer", "object_id": "1"},
        ]))

        assert observe(loop, None, "q").hops == 2

    def test_objects_are_distinct(self):
        """OVER-FETCHING IS THE QUESTION, and three steps against one
        object is not the same as three objects. Counting rows rather
        than objects would make a careful agent look wasteful."""
        loop = _Loop(_Result([
            {"step": "get_field", "object_type": "Customer", "object_id": "1"},
            {"step": "get_field", "object_type": "Customer", "object_id": "1"},
            {"step": "get_field", "object_type": "Customer", "object_id": "2"},
        ]))

        assert observe(loop, None, "q").objects == 2

    def test_the_same_id_in_two_types_is_two_objects(self):
        # Ids are unique within a type, not across them. Keying on the
        # id alone would merge a Customer and a Transaction.
        loop = _Loop(_Result([
            {"step": "get_field", "object_type": "Customer", "object_id": "1"},
            {"step": "get_field", "object_type": "Transaction", "object_id": "1"},
        ]))

        assert observe(loop, None, "q").objects == 2

    def test_the_step_mix_is_recorded(self):
        # Whether aggregates get chosen is one of the four questions,
        # and it is answered by which step names appear.
        loop = _Loop(_Result([
            {"step": "aggregate_object"},
            {"step": "get_object", "object_type": "C", "object_id": "1"},
        ]))

        assert observe(loop, None, "q").steps == {"aggregate_object": 1, "get_object": 1}

    def test_steps_without_an_object_do_not_count_as_one(self):
        # A completeness_check or a rejection has no object_id, and
        # counting it as an object would inflate over-fetching.
        loop = _Loop(_Result([{"step": "completeness_check", "note": "..."}]))

        assert observe(loop, None, "q").objects == 0


class TestOutcomes:
    def test_running_out_of_hops_is_recorded(self):
        loop = _Loop(_Result([{"step": "get_object", "object_id": "1"}], hit_max_hops=True))

        assert observe(loop, None, "q").capped is True

    def test_a_duplicate_stop_is_not_mistaken_for_finishing(self):
        """THE BUG A REAL RUN EXPOSED.

        A first version reported "answered 3/3" for runs that had
        stopped on consecutive duplicates, because a duplicate-stop
        just breaks the loop and sets no flag -- exactly as a
        deliberate finish does. The two are indistinguishable from the
        result, so the harness now reports the REJECTIONS instead of
        guessing at intent.
        """
        loop = _Loop(_Result([
            {"step": "get_field", "object_type": "T", "object_id": "3"},
            {"step": "rejected_duplicate", "note": "..."},
            {"step": "rejected_duplicate", "note": "..."},
        ]))

        observation = observe(loop, None, "q")

        assert observation.capped is False
        assert observation.steps["rejected_duplicate"] == 2

    def test_an_ordinary_failure_is_recorded_not_raised(self):
        """A prompt variant that breaks the agent is a FINDING. Losing
        the other runs to it would be the harness getting in the way of
        its own measurement."""
        loop = _Loop(raises=ValueError("something went wrong"))

        observation = observe(loop, None, "q")

        assert observation.capped is False
        assert observation.hops == 0

    def test_an_unreachable_model_stops_everything(self):
        # NOT an observation: every question fails the same way, so
        # continuing would print one connection error twelve times and
        # call it a measurement.
        loop = _Loop(raises=LLMUnavailable("no model"))

        with pytest.raises(LLMUnavailable):
            observe(loop, None, "q")


class TestReporting:
    def test_the_range_is_shown_beside_the_median(self):
        """A MEAN WOULD HIDE THE INTERESTING RESULT. One run taking
        nine hops where the others take two is the finding, and
        averaging it into 4.3 loses both facts."""
        runs = [
            Observation("q", hops=2, objects=1, seconds=1.0),
            Observation("q", hops=2, objects=1, seconds=1.0),
            Observation("q", hops=9, objects=1, seconds=5.0),
        ]

        report = _summarise(runs)

        assert "median 2" in report
        assert "range 2-9" in report

    def test_it_says_how_many_runs_ran_out_of_hops(self):
        runs = [
            Observation("q", hops=1, objects=1, capped=False),
            Observation("q", hops=20, objects=1, capped=True),
        ]

        assert "capped   1/2" in _summarise(runs)

    def test_rejections_are_reported_as_a_headline(self):
        # A run spending half its hops being told "no" is the finding.
        runs = [
            Observation("q", hops=4, objects=1,
                        steps={"get_field": 2, "rejected_duplicate": 2}),
        ]

        assert "rejected median 2 step(s)" in _summarise(runs)


class TestQuestionSelection:
    """Running one question rather than four.

    ON A SLOW MODEL THIS IS THE DIFFERENCE BETWEEN FIVE MINUTES AND
    FORTY. The first real run took 245 seconds for the simplest
    question and timed out on the third, so isolating one variable has
    to be cheap or it will not be done.
    """

    def test_every_question_has_a_unique_label(self):
        # The labels are the interface --only presents, so a duplicate
        # would make one of them unreachable.
        from scripts.measure_prompts import QUESTIONS

        labels = [label for label, _ in QUESTIONS]
        assert len(labels) == len(set(labels))

    def test_the_labels_are_the_ones_documented(self):
        # Pinned because they appear in BACKLOG.md's findings and in
        # the instructions a person follows. Renaming one silently
        # would make a recorded result unreproducible.
        from scripts.measure_prompts import QUESTIONS

        assert [label for label, _ in QUESTIONS] == [
            "single_field", "one_hop", "aggregate", "multi_object",
        ]
