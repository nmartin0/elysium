"""The answer is the one long thing the model writes (19 October): a
limit on its length, on by default and said when it bites; a switch
asking for brief answers, off until measured; and the bench grading
the answer itself, so a shorter one cannot quietly drop its facts."""

import pytest
import requests

import adapters.ollama_adapter as ollama_module
from adapters.ollama_adapter import OllamaAdapter
from adapters.vllm_adapter import VLLMAdapter
from core.agent.evaluation import EvalCase, ExpectedAggregate, ExpectedFact, answer_states
from core.llm.agent_features import features_from_config
from core.llm.synthesis_prompt import CUT_SHORT_NOTE, synthesize_insight
from core.request_context import TokenUsage

RECORDS = [{"object_type": "Customer", "object_id": "cust_001", "field": "email",
            "value": "ada.okafor@example.com"}]


def _capturing(body):
    sent = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return body

    def post(url, json=None, headers=None, timeout=None):
        sent.update(json)
        return Response()
    return post, sent


class TestTheSettings:
    def test_brief_answers_is_off_and_the_limit_is_on_unless_said(self):
        features = features_from_config({})
        assert features.brief_answers is False and features.answer_max_tokens == 400

    def test_both_can_be_set(self):
        features = features_from_config({"brief_answers": True, "answer_max_tokens": 120})
        assert features.brief_answers and features.answer_max_tokens == 120
        assert "brief_answers" in features.names_on

    def test_no_limit_is_null(self):
        assert features_from_config({"answer_max_tokens": None}).answer_max_tokens is None

    @pytest.mark.parametrize("limit", [0, 31, 5000, "400", True, 1.5])
    def test_a_limit_that_guards_nothing_is_refused(self, limit):
        with pytest.raises(ValueError, match="answer_max_tokens"):
            features_from_config({"answer_max_tokens": limit})


class TestOllama:
    def _adapter(self, **connection):
        return OllamaAdapter("m", {"base_url": "http://ollama.invalid/api/chat", **connection})

    def test_an_answer_is_capped_where_a_limit_is_set(self, monkeypatch):
        post, sent = _capturing({"message": {"content": "hi"}, "done_reason": "stop"})
        monkeypatch.setattr(ollama_module.requests, "post", post)

        self._adapter(prose_max_tokens=200).chat("s", "u")

        assert sent["options"]["num_predict"] == 200

    def test_a_step_keeps_its_own_cap(self, monkeypatch):
        post, sent = _capturing({"message": {"content": "{}"}, "done_reason": "stop"})
        monkeypatch.setattr(ollama_module.requests, "post", post)

        self._adapter(prose_max_tokens=200).chat("s", "u", json_mode=True)

        assert sent["options"]["num_predict"] == 768

    def test_no_limit_unless_set(self, monkeypatch):
        post, sent = _capturing({"message": {"content": "hi"}})
        monkeypatch.setattr(ollama_module.requests, "post", post)

        self._adapter().chat("s", "u")

        assert "num_predict" not in sent.get("options", {})

    def test_stopping_at_the_limit_is_reported(self, monkeypatch):
        post, _ = _capturing({"message": {"content": "Ada's email is"}, "done_reason": "length",
                              "eval_count": 200})
        monkeypatch.setattr(ollama_module.requests, "post", post)
        usage = TokenUsage()

        self._adapter(prose_max_tokens=200).chat("s", "u", usage=usage.for_part("answer"))

        assert usage.last("answer").stopped_at_limit is True


class TestOpenAIStyle:
    def test_max_tokens_and_finish_reason(self, monkeypatch):
        post, sent = _capturing({"choices": [{"message": {"content": "hi"}, "finish_reason": "length"}]})
        monkeypatch.setattr(requests, "post", post)
        usage = TokenUsage()

        VLLMAdapter("m", {"base_url": "http://gpu/v1/chat/completions", "prose_max_tokens": 150}).chat(
            "s", "u", usage=usage)

        assert sent["max_tokens"] == 150
        assert usage.records[0].stopped_at_limit is True

    def test_a_json_reply_is_not_given_the_answers_limit(self, monkeypatch):
        post, sent = _capturing({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})
        monkeypatch.setattr(requests, "post", post)

        VLLMAdapter("m", {"base_url": "http://gpu/v1/chat/completions", "prose_max_tokens": 150}).chat(
            "s", "u", json_mode=True)

        assert "max_tokens" not in sent


class _Answer:
    max_concurrent_requests = 1

    def __init__(self, text, stopped=False):
        self.text, self.stopped, self.system = text, stopped, None

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        self.system = system_prompt
        if usage is not None:
            usage.add(10, 5, seconds=0.1, stopped_at_limit=self.stopped)
        return self.text


class TestTheAnswer:
    def test_a_cut_answer_says_so(self):
        client = _Answer("Ada Okafor's email is ada.okafor@example.com [R1] and she", stopped=True)

        answer = synthesize_insight(client, "q", RECORDS, usage=TokenUsage())

        assert answer.endswith(CUT_SHORT_NOTE)

    def test_a_whole_answer_does_not(self):
        answer = synthesize_insight(_Answer("It is ada.okafor@example.com [R1]."), "q", RECORDS,
                                    usage=TokenUsage())

        assert CUT_SHORT_NOTE not in answer

    def test_brief_is_asked_for_only_when_switched_on(self):
        on, off = _Answer("x [R1]"), _Answer("x [R1]")
        synthesize_insight(on, "q", RECORDS, brief=True)
        synthesize_insight(off, "q", RECORDS)

        assert "BE BRIEF" in on.system and "BE BRIEF" not in off.system


class TestTheAnswerIsGraded:
    CASE = EvalCase(name="c", query="q", user_id="u",
                    expected_facts=(ExpectedFact("Transaction", "2", "amount", "199"),))

    def test_stated_or_not(self):
        assert answer_states(self.CASE, "It was 199 [R1].") is True
        assert answer_states(self.CASE, "It was large [R1].") is False

    def test_a_citation_tag_is_not_a_value(self):
        count = EvalCase(name="c", query="q", user_id="u", expected_facts=(),
                         expected_aggregates=(ExpectedAggregate("Transaction", "count", "2"),))
        assert answer_states(count, "She has some transactions [R2].") is False
        assert answer_states(count, "She has 2 transactions [R1].") is True

    def test_nothing_to_check_is_not_a_pass(self):
        assert answer_states(self.CASE, None) is None
        assert answer_states(EvalCase(name="c", query="q", user_id="u", expected_facts=()),
                             "anything") is None


def test_only_the_answers_client_is_given_the_limit(synced_deployment):
    from core.deployment_loader import build_generation

    generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                  synced_deployment.log_dir)

    def innermost(client):
        while hasattr(client, "_wrapped"):
            client = client._wrapped
        return client

    assert innermost(generation.synthesis_client).prose_num_predict == 400
    assert innermost(generation.loop.client).prose_num_predict is None


class TestTheBriefVerdict:
    def _arm(self, said, tokens):
        from scripts.feature_bench import ORIGINAL

        return {name: {"passed": 1, "trials": 1, "hops": [2], "seconds": [60.0],
                       "said": [said], "answer_tokens": [tokens]} for name in ORIGINAL}

    def test_on_when_shorter_and_nothing_lost(self):
        from scripts.feature_bench import _brief_verdict

        assert _brief_verdict(self._arm(True, 90), self._arm(True, 40))[0] == "ON"

    def test_off_when_an_answer_stops_stating_its_facts(self):
        from scripts.feature_bench import _brief_verdict

        verdict, why = _brief_verdict(self._arm(True, 90), self._arm(False, 20))
        assert verdict == "OFF" and "stopped stating" in why

    def test_off_when_not_shorter(self):
        from scripts.feature_bench import _brief_verdict

        assert _brief_verdict(self._arm(True, 40), self._arm(True, 45))[0] == "OFF"
