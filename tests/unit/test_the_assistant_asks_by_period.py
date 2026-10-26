"""The assistant's aggregate step takes a period (BLOCKING.md item 3's
time-series reads, part 3): "how did sales go week by week" is one step
that returns one total per week, where before it had no way to ask.

Held at each place a step passes through: the grammar the model server
compiles (step_schema), the parser that checks a reply (next_step's
validation), the loop that carries it out, and the sentence the answer's
account of the work is written from."""

import datetime

import jsonschema
import pytest

from core.agent.answer_context import read_back
from core.llm.agent_step_prompt import validated_step
from core.llm.step_schema import step_schema
from tests.unit.test_step_schema import SCHEMA

WEEKLY = {"step": "aggregate_object", "object_type": "Transaction", "filter": {},
          "aggregate": "sum", "field_name": "amount", "group_by": "transaction_date",
          "period": "week"}


def _admits(step, schema=SCHEMA):
    try:
        jsonschema.validate(step, step_schema(schema, [], False, {}))
    except jsonschema.ValidationError:
        return False
    return True


class TestTheGrammar:
    def test_a_type_with_a_date_may_be_totalled_per_period(self):
        assert _admits(WEEKLY)

    def test_only_the_periods_there_are(self):
        assert not _admits({**WEEKLY, "period": "fortnight"})

    def test_a_type_with_no_date_is_offered_no_period(self):
        assert not _admits({"step": "aggregate_object", "object_type": "Customer",
                            "filter": {}, "aggregate": "count", "group_by": "region",
                            "period": "week"})


class TestTheParser:
    def test_the_period_is_kept(self):
        assert validated_step(WEEKLY)["period"] == "week"

    def test_an_unknown_period_finishes_rather_than_guessing(self):
        assert validated_step({**WEEKLY, "period": "fortnight"})["step"] == "finish"


class TestTheLoop:
    @pytest.fixture
    def loop_and_user(self, synced_deployment, monkeypatch):
        from core.deployment_loader import build_generation
        from core.intermediate_layer.auth import resolve_user_record

        generation = build_generation(synced_deployment.config_dir, synced_deployment.data_dir,
                                      synced_deployment.log_dir)
        user = resolve_user_record(generation.config.users, "user_alice",
                                   generation.config.security_attribute)
        asked = {}

        def aggregate_by_field(_user, _type, _conditions, **arguments):
            asked.update(arguments)
            return {datetime.date(2026, 5, 4): 3, datetime.date(2026, 5, 11): 0}

        monkeypatch.setattr(generation.loop.mediator, "aggregate_by_field", aggregate_by_field)
        return generation.loop, user, asked

    def test_the_period_reaches_the_mediator_and_each_period_is_named_by_its_date(self, loop_and_user):
        loop, user, asked = loop_and_user
        schema = loop.mediator.visible_schema(user, for_agent=True)

        result = loop._step_aggregate_object({**WEEKLY, "filter": {}}, user, schema, [])

        assert asked["period"] == "week"
        # JSON cannot write a date as a key; the model reads this as JSON.
        assert result == {"2026-05-04": 3, "2026-05-11": 0}

    def test_two_periods_are_two_different_steps(self):
        from core.agent.agentic_loop import _step_signature

        assert _step_signature(WEEKLY) != _step_signature({**WEEKLY, "period": "month"})


def test_the_account_of_the_work_says_per_what():
    said = " ".join(read_back([{**WEEKLY, "result": {}}], SCHEMA))
    assert "per week" in said
