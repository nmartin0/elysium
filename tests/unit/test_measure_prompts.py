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
    def test_running_out_of_hops_is_not_answered(self):
        loop = _Loop(_Result([{"step": "get_object", "object_id": "1"}], hit_max_hops=True))

        assert observe(loop, None, "q").answered is False

    def test_an_ordinary_failure_is_recorded_not_raised(self):
        """A prompt variant that breaks the agent is a FINDING. Losing
        the other runs to it would be the harness getting in the way of
        its own measurement."""
        loop = _Loop(raises=ValueError("something went wrong"))

        observation = observe(loop, None, "q")

        assert observation.answered is False
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
            Observation("q", hops=2, objects=1, answered=True, seconds=1.0),
            Observation("q", hops=2, objects=1, answered=True, seconds=1.0),
            Observation("q", hops=9, objects=1, answered=True, seconds=5.0),
        ]

        report = _summarise(runs)

        assert "median 2" in report
        assert "range 2-9" in report

    def test_it_says_how_many_runs_answered(self):
        runs = [
            Observation("q", hops=1, objects=1, answered=True),
            Observation("q", hops=1, objects=1, answered=False),
        ]

        assert "answered 1/2" in _summarise(runs)
