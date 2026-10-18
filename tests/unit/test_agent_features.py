"""
The four agent switches waiting on a measurement (core/llm/agent_features.py).

Each is built and OFF. These tests say two things about every one:

  OFF CHANGES NOTHING -- the system prompt is byte-for-byte what it was,
  the step schema admits nothing new, and the new steps are unknown.

  ON DOES WHAT IT SAYS -- with a scripted model over the real mediator
  (the shared Author/Book fixture: auth_001 is org-a with books 1 and 2,
  auth_002 org-b with book 3).

Whether turning one on HELPS is not a question for these tests. That
is scripts/feature_bench.py, on a real model.
"""

import json

import pytest

from core.agent.agentic_loop import AgentLoop, StopReason
from core.agent.evaluation import EvalCase, ExpectedMemory, grade
from core.filters import FilterError, agent_conditions
from core.intermediate_layer.auth import resolve_user_record
from core.llm.agent_features import OFF, AgentFeatures, features_from_config
from core.llm.agent_step_prompt import (
    FILTER_OPERATORS_SECTION,
    FREE_TEXT_SECTION,
    MEANING_SECTION,
    REMEMBER_SECTION,
    _build_system_prompt,
    validated_step,
)
from core.llm.step_schema import step_schema
from core.memory.guard import MemoryGuard
from core.memory.store import MemoryStore
from tests.conftest import TEST_SCHEMA, author_book_mediator, scripted_llm_client

READ_ALL = ["read:Author", "read:Author.author_id", "read:Author.org_id", "read:Author.name",
            "read:Author.books", "read:Book", "read:Book.book_id", "read:Book.title",
            "read:Book.year", "read:Book.author_id"]
ROLES = {"reader": {"allowed_actions": READ_ALL}}
USERS = {"alice": {"org_id": "org-a", "role": "reader"}}
ALL_ON = AgentFeatures(filter_operators=True, search_result_cap=1, free_text_search=True,
                       remember_from_query=True, meaning_search=True)


def _alice():
    return resolve_user_record(USERS, "alice", "org_id")


@pytest.fixture
def mediator(test_db_path, test_schema):
    return author_book_mediator(test_db_path, test_schema, ROLES)


@pytest.fixture
def guard(mediator, tmp_path):
    return MemoryGuard(MemoryStore(tmp_path / "memories.db"), mediator, ROLES)


def _run(mediator, steps, features, query="test query", memory=None):
    loop = AgentLoop(scripted_llm_client([*steps, {"step": "finish"}]), mediator,
                     memory=memory, features=features)
    return loop.run(_alice(), query)


def _entries(result, kind):
    return [entry for entry in result.gathered if entry["step"] == kind]


class TestConfig:
    def test_absent_is_off(self):
        assert features_from_config({}) == OFF
        assert OFF.names_on == ()

    def test_each_switch_is_read(self):
        features = features_from_config({"filter_operators": True, "search_result_cap": 5,
                                         "free_text_search": True, "remember_from_query": True,
                                         "meaning_search": True})
        assert features.names_on == ("filter_operators", "search_result_cap=5",
                                     "free_text_search", "remember_from_query", "meaning_search")

    @pytest.mark.parametrize("block", [{"filter_operators": "yes"}, {"search_result_cap": 0},
                                       {"search_result_cap": True}, {"search_result_cap": "5"}])
    def test_a_malformed_switch_fails_at_load(self, block):
        with pytest.raises(ValueError):
            features_from_config(block)


class TestOffChangesNothing:
    def test_the_prompt_carries_no_section_of_a_switch_that_is_off(self):
        """BYTE-IDENTITY WITH THE PROMPT BEFORE THE SWITCHES EXISTED was
        measured when they were added -- the sha256 of this prompt from
        the previous commit and from this one matched. Not pinned as a
        hash, which every legitimate prompt edit would break; pinned as
        what the switches add being absent, which only they can break."""
        prompt = _build_system_prompt(TEST_SCHEMA, [], False, {})
        for section in (FILTER_OPERATORS_SECTION, FREE_TEXT_SECTION, REMEMBER_SECTION,
                        MEANING_SECTION):
            assert section not in prompt
        assert '"search_text"' not in prompt and '"remember"' not in prompt
        assert '"search_meaning"' not in prompt

    def test_on_the_prompt_grows(self):
        """THE CONTROL for the one above: the sections exist and are
        gated, so equality is not a property of the call shape."""
        on = _build_system_prompt(TEST_SCHEMA, [], False, {}, features=ALL_ON)
        assert '"search_text"' in on and '"remember"' in on and '"not_in"' in on

    def test_the_cap_alone_leaves_the_prompt_alone(self):
        assert (_build_system_prompt(TEST_SCHEMA, [], False, {},
                                     features=AgentFeatures(search_result_cap=3))
                == _build_system_prompt(TEST_SCHEMA, [], False, {}))

    def test_the_new_steps_are_unrecognised(self):
        for step in ({"step": "search_text", "object_type": "Book", "text": "x"},
                     {"step": "remember", "object_type": "Book", "object_id": 1, "text": "x"},
                     {"step": "search_meaning", "object_type": "Book", "text": "x"}):
            assert validated_step(step).get("fallback") is not None
            assert validated_step(step, features=ALL_ON) == step

    def test_the_step_schema_is_unchanged(self):
        off = step_schema(TEST_SCHEMA, [], False, {})
        assert {variant["properties"]["step"]["const"] for variant in off["anyOf"]}.isdisjoint(
            {"search_text", "remember"})
        assert '"not_in"' not in json.dumps(off)
        assert '"not_in"' in json.dumps(step_schema(TEST_SCHEMA, [], False, {},
                                                    features=AgentFeatures(filter_operators=True)))
        on = step_schema(TEST_SCHEMA, [], False, {}, features=ALL_ON)
        names = {variant["properties"]["step"]["const"] for variant in on["anyOf"]}
        assert {"search_text", "remember"} <= names

    def test_a_condition_is_refused_when_off(self, mediator):
        result = _run(mediator, [{"step": "search_object", "object_type": "Book",
                                  "filter": {"year": {"min": 1843}}}], OFF)
        assert _entries(result, "rejected_invalid_step")
        assert not _entries(result, "search_object")


class TestFilterOperators:
    ON = AgentFeatures(filter_operators=True)

    def test_scalars_stay_equality(self):
        [condition] = agent_conditions({"title": "x"})
        assert (condition.operator, condition.value) == ("equals", "x")

    @pytest.mark.parametrize("value, operator", [
        ({"in": [1]}, "in"), ({"not_in": [1]}, "not_in"), ({"min": 1}, "range"),
        ({"min": 1, "max": 2}, "range"), ({"start": "2026-01-01"}, "date_range"),
        ({"contains": "x"}, "contains")])
    def test_each_condition_maps_to_one_operator(self, value, operator):
        assert agent_conditions({"f": value})[0].operator == operator

    @pytest.mark.parametrize("value", [{}, {"in": [1], "min": 2}, {"between": [1, 2]}])
    def test_anything_else_is_refused_naming_the_shapes(self, value):
        with pytest.raises(FilterError, match='"in"'):
            agent_conditions({"f": value})

    def test_a_range_finds_by_range(self, mediator):
        result = _run(mediator, [{"step": "search_object", "object_type": "Book",
                                  "filter": {"year": {"min": 1843}}}], self.ON)
        assert _entries(result, "search_object")[0]["result"] == [1]

    def test_in_finds_either(self, mediator):
        result = _run(mediator, [{"step": "search_object", "object_type": "Book",
                                  "filter": {"year": {"in": [1842, 1843]}}}], self.ON)
        assert sorted(_entries(result, "search_object")[0]["result"]) == [1, 2]

    def test_a_condition_never_widens_what_a_caller_sees(self, mediator):
        """Book 3 (1952) is org-b's: a range over it finds nothing."""
        result = _run(mediator, [{"step": "search_object", "object_type": "Book",
                                  "filter": {"year": {"min": 1900}}}], self.ON)
        assert _entries(result, "search_object")[0]["result"] == []

    def test_aggregates_take_conditions_too(self, mediator):
        result = _run(mediator, [{"step": "aggregate_object", "object_type": "Book",
                                  "filter": {"year": {"max": 1842}}, "aggregate": "count"}],
                      self.ON)
        assert _entries(result, "aggregate_object")[0]["result"] == 1

    def test_a_malformed_condition_is_a_mistake_to_correct(self, mediator):
        result = _run(mediator, [{"step": "search_object", "object_type": "Book",
                                  "filter": {"year": {"between": [1, 2]}}}], self.ON)
        [rejected] = _entries(result, "rejected_invalid_step")
        assert "not a condition" in rejected["note"] and '{"min": ..' in rejected["note"]

    def test_a_bare_list_is_still_refused(self, mediator):
        result = _run(mediator, [{"step": "search_object", "object_type": "Book",
                                  "filter": {"year": [1842, 1843]}}], self.ON)
        [rejected] = _entries(result, "rejected_invalid_step")
        assert '{"in": [..]}' in rejected["note"]


class TestSearchResultCap:
    def test_over_the_cap_shows_the_first_and_says_how_many(self, mediator):
        result = _run(mediator, [{"step": "search_object", "object_type": "Book",
                                  "filter": {"author_id": "auth_001"}}],
                      AgentFeatures(search_result_cap=1))
        [entry] = _entries(result, "search_object")
        assert len(entry["result"]) == 1 and entry["total"] == 2
        assert "aggregate_object" in entry["shown"]

    def test_at_or_under_the_cap_nothing_changes(self, mediator):
        """THE CONTROL: a cap of 2 over two results adds nothing."""
        result = _run(mediator, [{"step": "search_object", "object_type": "Book",
                                  "filter": {"author_id": "auth_001"}}],
                      AgentFeatures(search_result_cap=2))
        [entry] = _entries(result, "search_object")
        assert "total" not in entry and len(entry["result"]) == 2


class TestFreeTextSearch:
    ON = AgentFeatures(free_text_search=True)

    def test_part_of_a_value_finds_it(self, mediator):
        result = _run(mediator, [{"step": "search_text", "object_type": "Book",
                                  "text": "Sketch"}], self.ON)
        assert _entries(result, "search_text")[0]["result"] == [2]

    def test_it_sees_only_what_the_caller_sees(self, mediator):
        result = _run(mediator, [{"step": "search_text", "object_type": "Book",
                                  "text": "Glossary"}], self.ON)
        assert _entries(result, "search_text")[0]["result"] == []

    def test_off_it_is_not_a_step(self, mediator):
        result = _run(mediator, [{"step": "search_text", "object_type": "Book",
                                  "text": "Sketch"}], OFF)
        assert not _entries(result, "search_text")


class TestRememberFromQuery:
    ON = AgentFeatures(remember_from_query=True)
    STEP = {"step": "remember", "object_type": "Author", "object_id": "auth_001",
            "text": "prefers email"}

    def test_a_question_asking_to_remember_is_remembered(self, mediator, guard):
        result = _run(mediator, [self.STEP], self.ON,
                      query="Remember that Ada prefers email", memory=guard)
        assert result.stop_reason == StopReason.FINISHED
        assert [m.text for m, _ in guard.visible(_alice(), "Author", "auth_001")] == \
            ["prefers email"]

    def test_a_question_that_did_not_ask_records_nothing(self, mediator, guard):
        """THE GUARANTEE: E-14's "written only when a person asks"
        holds whatever the model decides."""
        result = _run(mediator, [self.STEP], self.ON, query="What is Ada's email?",
                      memory=guard)
        assert guard.visible(_alice(), "Author", "auth_001") == []
        assert "did not ask" in _entries(result, "rejected_invalid_step")[0]["note"]

    def test_only_once_per_answer(self, mediator, guard):
        second = {**self.STEP, "text": "and likes tea"}
        _run(mediator, [self.STEP, second], self.ON,
             query="Remember that Ada prefers email", memory=guard)
        assert len(guard.visible(_alice(), "Author", "auth_001")) == 1

    def test_an_object_the_caller_cannot_see_is_not_written_about(self, mediator, guard):
        _run(mediator, [{**self.STEP, "object_id": "auth_002"}], self.ON,
             query="Remember that Grace prefers email", memory=guard)
        assert guard.store.about("Author", "auth_002") == []

    def test_graded_on_the_object(self, mediator, guard):
        result = _run(mediator, [self.STEP], self.ON,
                      query="Remember that Ada prefers email", memory=guard)
        case = EvalCase("r", "q", "alice", (),
                        expected_memories=(ExpectedMemory("Author", "auth_001", "email"),))
        assert grade(case, result).passed
        wrong = EvalCase("r", "q", "alice", (),
                         expected_memories=(ExpectedMemory("Author", "auth_002"),))
        assert not grade(wrong, result).passed


class TestMeaningSearch:
    """R45, behind features.meaning_search: the agent ranks by meaning
    through the same service Browse does (core/meaning_search.py) -- a
    stand-in here; the real one is tested end to end."""

    ON = AgentFeatures(meaning_search=True)
    STEP = {"step": "search_meaning", "object_type": "Book", "text": "a long poem"}

    class Service:
        def __init__(self, ranked):
            self.ranked = ranked
            self.asked = []

        def related(self, mediator, user_record, object_type, text, k, context=None, exclude=None):
            self.asked.append((user_record.user_id, object_type, text, k))
            return self.ranked

    def _run(self, mediator, service, features=None):
        loop = AgentLoop(scripted_llm_client([self.STEP, {"step": "finish"}]), mediator,
                         features=features or self.ON, meaning=service)
        return loop.run(_alice(), "which books read like a long poem?")

    def test_the_nearest_records_come_back_nearest_first_and_marked_a_ranking(self, mediator):
        from core.meaning_search import Ranked

        service = self.Service(Ranked(True, ids=[2, 1]))
        [entry] = _entries(self._run(mediator, service), "search_meaning")
        assert entry["result"] == [2, 1]
        assert "do not count it" in entry["order"]
        assert service.asked == [("alice", "Book", "a long poem", AgentLoop.MEANING_K)]

    def test_when_it_cannot_answer_the_model_is_told_why_not_handed_an_empty_list(self, mediator):
        from core.meaning_search import MODEL_DOWN, Ranked

        [entry] = _entries(self._run(mediator, self.Service(Ranked(False, reason=MODEL_DOWN))),
                           "search_meaning")
        assert entry["result"] == [] and entry["note"] == MODEL_DOWN

    def test_with_no_embedder_it_is_not_offered(self, mediator):
        from core.meaning_search import NOT_OFFERED

        [entry] = _entries(self._run(mediator, None), "search_meaning")
        assert entry["note"] == NOT_OFFERED

    def test_off_it_is_not_a_step(self, mediator):
        from core.meaning_search import Ranked

        service = self.Service(Ranked(True, ids=[1]))
        assert not _entries(self._run(mediator, service, features=OFF), "search_meaning")
        assert service.asked == []

    def test_only_types_searchable_by_meaning_are_marked_and_offered(self):
        schema = json.loads(json.dumps(TEST_SCHEMA))
        for definition in schema.values():
            definition["searchable_by_meaning"] = False
        schema["Book"]["searchable_by_meaning"] = True
        prompt = _build_system_prompt(schema, [], False, {}, features=self.ON)
        assert prompt.count("(search by meaning)") == 1
        assert MEANING_SECTION in prompt
        variants = step_schema(schema, [], False, {}, features=self.ON)["anyOf"]
        offered = {variant["properties"]["object_type"]["const"] for variant in variants
                   if variant["properties"]["step"]["const"] == "search_meaning"}
        assert offered == {"Book"}
        off = _build_system_prompt(schema, [], False, {})
        assert "(search by meaning)" not in off, "off, the prompt is what it was"

    def test_the_answer_says_these_are_the_nearest_not_how_many_there_are(self):
        from core.agent.answer_context import read_back

        sentences = " ".join(read_back([{**self.STEP, "result": [2, 1]}], TEST_SCHEMA))
        assert "close in meaning to 'a long poem'" in sentences
        assert "read the 2 nearest" in sentences
