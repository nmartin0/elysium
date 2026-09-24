"""
A model-written value of the wrong shape is a mistake, not an outage
(AL-1).

THE CRASH. `_step_signature()` runs BEFORE `_execute_step()`, outside
the try/except that turns a bad step into a recoverable mistake, and
built a frozenset over the model's own filter dict. A list or dict
value raised `TypeError: unhashable type` straight out of run(), so the
whole /query request failed. Three shapes reproduce it, and a model
produces all three naturally -- `{"code": ["A-01", "A-02"]}` is how
anyone would write "in [a, b]" without being told the grammar.

FIXING THE SIGNATURE ALONE WAS NOT ENOUGH, which the probe showed
immediately: the values then reached the ADAPTER, which raised
sqlite3.ProgrammingError -- also outside the loop's caught set, also
killing the request. Both halves are needed, which is what the audit
said.

THE use_tool BRANCH ALREADY KNEW THE ANSWER. Its comment explains that
function args "can contain UNHASHABLE values ... JSON serialization
(sort_keys=True for determinism) handles nested lists/dicts safely and
still produces a stable, hashable signature". Correct reasoning,
applied to one of six step kinds.

WHY A ValueError AND NOT A REFUSAL. The loop already turns ValueError
into a recoverable mistake: the model is told what was wrong and tries
again, capped by max_consecutive_invalid_steps. A malformed step is the
model's to fix, not the request's to die of -- and the last test here
shows it correcting itself and reaching the answer.
"""

import json
import sqlite3
from unittest.mock import MagicMock

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.agent.agentic_loop import AgentLoop, _step_signature, check_step_values
from core.intermediate_layer.auth import UserRecord
from core.ontology.mediator import DataMediator

SCHEMA = {
    "Account": {
        "id_field": "id", "security": {"field": "region"},
        "storage": {"silo": "p", "table": "t", "id_column": "id"},
        "fields": {"id": {"type": "data"}, "code": {"type": "data"},
                    "region": {"type": "data"}},
    }
}

BAD_SHAPES = [
    pytest.param({"step": "search_object", "object_type": "Account",
                  "filter": {"code": ["A-01", "A-02"]}}, id="filter-value-is-a-list"),
    pytest.param({"step": "get_field", "object_type": "Account",
                  "object_id": ["a1", "a2"], "field_name": "code"}, id="object_id-is-a-list"),
    pytest.param({"step": "aggregate_object", "object_type": "Account",
                  "aggregate": "count", "filter": {"code": {"x": 1}}},
                 id="filter-value-is-a-dict"),
    pytest.param({"step": "search_around", "object_type": "Account",
                  "filter": {"code": {"x": 1}}, "link_field": "owner"},
                 id="search_around-filter-dict"),
    pytest.param({"step": "get_object", "object_type": "Account",
                  "object_ids": ["a1"], "field_names": [["code"]]},
                 id="field_names-holds-a-list"),
]


@pytest.fixture
def mediator(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, code TEXT, region TEXT)")
    conn.execute("INSERT INTO t VALUES ('a1','A-01','us-west')")
    conn.commit()
    conn.close()
    grants = ["read:Account"] + [f"read:Account.{f}" for f in SCHEMA["Account"]["fields"]]
    return DataMediator(SCHEMA, {"p": SQLiteReadAdapter({"path": source})},
                        {"Account": "p"}, {"r": {"allowed_actions": grants}})


@pytest.fixture
def user():
    return UserRecord(user_id="u", security_value="us-west", role_name="r")


def _scripted(*steps):
    client = MagicMock()
    sequence = list(steps) + [{"step": "finish", "answer": "done"}]
    counter = {"i": 0}

    def chat(*a, **k):
        step = sequence[min(counter["i"], len(sequence) - 1)]
        counter["i"] += 1
        return json.dumps(step)
    client.chat.side_effect = chat
    return client


class TestTheRequestSurvives:
    @pytest.mark.parametrize("step", BAD_SHAPES)
    def test_a_bad_shape_does_not_end_the_request(self, mediator, user, step):
        result = AgentLoop(_scripted(step), mediator).run(user, "q")

        assert result is not None

    @pytest.mark.parametrize("step", BAD_SHAPES)
    def test_it_is_recorded_as_a_recoverable_mistake(self, mediator, user, step):
        """Not swallowed: the model is TOLD, which is what lets it try
        something else."""
        result = AgentLoop(_scripted(step), mediator).run(user, "q")

        rejected = [s for s in result.gathered
                    if s.get("step") == "rejected_invalid_step"]
        assert len(rejected) == 1

    def test_the_model_can_correct_itself_and_get_the_answer(self, mediator, user):
        """The whole point of a recoverable mistake."""
        result = AgentLoop(_scripted(
            {"step": "get_field", "object_type": "Account",
             "object_id": ["a1"], "field_name": "code"},
            {"step": "get_field", "object_type": "Account",
             "object_id": "a1", "field_name": "code"},
        ), mediator).run(user, "q")

        answers = [s.get("result") for s in result.gathered
                   if s.get("step") == "get_field"]
        assert answers == ["A-01"]


class TestTheSignatureItself:
    """The first half, tested directly: it must never raise, whatever
    the model writes."""

    @pytest.mark.parametrize("step", BAD_SHAPES)
    def test_a_signature_can_always_be_taken(self, step):
        _step_signature(step)

    def test_order_still_does_not_matter_for_sets(self):
        """The frozensets were there for a reason -- naming the same
        ids or fields in a different order is the same request -- and
        making values hashable must not cost that."""
        a = {"step": "get_object", "object_type": "Account",
             "object_ids": ["a1", "a2"], "field_names": ["code", "region"]}
        b = {"step": "get_object", "object_type": "Account",
             "object_ids": ["a2", "a1"], "field_names": ["region", "code"]}

        assert _step_signature(a) == _step_signature(b)

    def test_different_steps_still_differ(self):
        """A signature that collapsed everything would silently stop
        the agent after one step."""
        a = {"step": "get_field", "object_type": "Account",
             "object_id": "a1", "field_name": "code"}
        b = {"step": "get_field", "object_type": "Account",
             "object_id": "a2", "field_name": "code"}

        assert _step_signature(a) != _step_signature(b)


class TestTheShapeCheck:
    def test_good_steps_pass_untouched(self):
        for step in ({"step": "get_field", "object_type": "A", "object_id": "a1",
                       "field_name": "code"},
                      {"step": "search_object", "object_type": "A",
                       "filter": {"code": "A-01", "n": 3, "ok": True}},
                      {"step": "get_object", "object_type": "A",
                       "object_ids": ["a1", "a2"], "field_names": ["code"]}):
            check_step_values(step)

    def test_a_null_value_is_allowed(self):
        """None is a legitimate thing to filter on."""
        check_step_values({"step": "search_object", "object_type": "A",
                            "filter": {"code": None}})

    def test_the_message_names_the_field_and_the_type(self):
        """A recoverable mistake the model cannot understand is not
        recoverable."""
        with pytest.raises(ValueError, match=r"object_id.*list"):
            check_step_values({"object_id": ["a1", "a2"]})
