"""
The agent can read every type the ontology serves (PA001-X2, G12).

THE CRASH. The mediator coerces to the DECLARED type, so `decimal`
comes back as decimal.Decimal and `date` as datetime.date, and the step
prompt serialised gathered results with json.dumps, which raises
TypeError on both. In the SHIPPED configuration -- Transaction.amount
is declared decimal, deliberately, for money -- the agent could not
answer a question that read an amount or a date. The exception left the
loop and the /query request failed.

WHY NO TEST CAUGHT IT. Every existing agent test mocks the mediator and
returns floats and strings. The bug lives exactly in the gap between a
mocked mediator and a real one, so only driving the REAL loop over a
REAL mediator can see it. These tests do that.

AND IT ANSWERS THE RENDERING QUESTION ONCE. A decimal is stored at the
column's scale (49.990000000) and declared with decimal_places (2), so
the live path and the mirror showed the same money differently
(PA001-G12). The model now sees the DECLARED form on every path.
"""

import json
import sqlite3
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import UserRecord
from core.llm.prompt_values import dumps_gathered, render_value
from core.ontology.mediator import DataMediator

SCHEMA = {
    "Transaction": {
        "id_field": "id",
        "security": {"field": "region"},
        "storage": {"silo": "p", "table": "t", "id_column": "id"},
        "fields": {
            "id": {"type": "data"},
            "region": {"type": "data"},
            "amount": {"type": "data", "data_type": "decimal", "decimal_places": 2},
            "when_": {"type": "data", "data_type": "date"},
            "count_": {"type": "data", "data_type": "integer"},
            "score": {"type": "data", "data_type": "number"},
            "ok": {"type": "data", "data_type": "boolean"},
            "note": {"type": "data"},
        },
    }
}


@pytest.fixture
def mediator(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, amount TEXT, when_ TEXT, "
                 "count_ TEXT, score REAL, ok INTEGER, note TEXT, region TEXT)")
    conn.execute("INSERT INTO t VALUES ('t1','49.99','2026-05-01','3',2.5,1,'hi','us-west')")
    conn.commit()
    conn.close()
    grants = ["read:Transaction"] + [f"read:Transaction.{f}"
                                      for f in SCHEMA["Transaction"]["fields"]]
    return DataMediator(SCHEMA, {"p": SQLiteReadAdapter({"path": source})},
                        {"Transaction": "p"}, {"r": {"allowed_actions": grants}})


@pytest.fixture
def user():
    return UserRecord(user_id="u", security_value="us-west", role_name="r")


def _scripted(steps, seen=None):
    client = MagicMock()
    counter = {"i": 0}

    def chat(_system, user_message, *a, **k):
        if seen is not None:
            seen.append(user_message)
        step = steps[min(counter["i"], len(steps) - 1)]
        counter["i"] += 1
        return json.dumps(step)
    client.chat.side_effect = chat
    return client


class TestTheRealLoopOverARealMediator:
    @pytest.mark.parametrize("field", ["amount", "when_", "count_", "score", "ok", "note"])
    def test_every_declared_type_can_be_read(self, mediator, user, field):
        """amount (decimal) and when_ (date) were the crash; the rest
        are here so a future type cannot regress silently."""
        steps = [{"step": "get_field", "object_type": "Transaction",
                  "object_id": "t1", "field_name": field},
                 {"step": "finish", "answer": "done"}]

        AgentLoop(_scripted(steps), mediator).run(user, "what is it?")

    def test_get_object_over_every_type_at_once(self, mediator, user):
        """The shape that carries several declarations in one result."""
        steps = [{"step": "get_object", "object_type": "Transaction",
                  "object_ids": ["t1"],
                  "field_names": ["amount", "when_", "score", "note"]},
                 {"step": "finish", "answer": "done"}]

        AgentLoop(_scripted(steps), mediator).run(user, "what is it?")

    def test_the_model_is_shown_the_declared_scale(self, mediator, user):
        """Not the storage scale, and not a float."""
        seen = []
        steps = [{"step": "get_field", "object_type": "Transaction",
                  "object_id": "t1", "field_name": "amount"},
                 {"step": "finish", "answer": "done"}]

        AgentLoop(_scripted(steps, seen), mediator).run(user, "what is it?")

        prompts = [p for p in seen if "get_field" in p]
        assert prompts and '"49.99"' in prompts[-1]


class TestTheRenderer:
    def test_a_stored_scale_reads_as_the_declared_one(self):
        """PA001-G12: the mirror serves 49.990000000 where the live
        path serves 49.99. Both are the same money and now read the
        same."""
        assert render_value(Decimal("49.990000000"), {"decimal_places": 2}) == "49.99"
        assert render_value(Decimal("49.99"), {"decimal_places": 2}) == "49.99"

    def test_a_declared_scale_PADS_as_well_as_trims(self):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Ignoring
        decimal_places entirely still passed every test, because
        normalising 49.990000000 happens to give 49.99 too. Padding is
        where the declaration actually decides: 49.9 in a field
        declared to two places is 49.90, and a model reading prices
        should see the money, not the shortest spelling of it."""
        assert render_value(Decimal("49.9"), {"decimal_places": 2}) == "49.90"
        assert render_value(Decimal("50"), {"decimal_places": 2}) == "50.00"

    def test_no_decimal_is_ever_shown_in_exponent_form(self):
        """Decimal("50.00").normalize() is 5E+1. A model reading that
        as money is a plausible wrong answer, so every path formats
        with :f."""
        for value in (Decimal("50.00"), Decimal("1E+2"), Decimal("0.00001")):
            assert "E" not in render_value(value)
            assert "E" not in render_value(value, {"decimal_places": 2})

    def test_an_undeclared_decimal_is_normalised(self):
        assert render_value(Decimal("10.500000000")) == "10.5"

    def test_exactness_survives(self):
        """A float would not carry this, and money is why someone
        declared the field decimal."""
        big = Decimal("12345678901234567.89")

        assert render_value(big, {"decimal_places": 2}) == "12345678901234567.89"

    def test_dates_and_times_are_iso(self):
        import datetime

        assert render_value(datetime.date(2026, 5, 1)) == "2026-05-01"
        assert render_value(datetime.datetime(2026, 5, 1, 9, 30)) == "2026-05-01T09:30:00"
        assert render_value(datetime.time(9, 30)) == "09:30:00"

    def test_ordinary_values_pass_through_untouched(self):
        for value in ("text", 3, 2.5, True, None, []):
            assert render_value(value) == value

    def test_nested_results_are_rendered_per_field(self):
        schema = {"Transaction": {"fields": {"amount": {"decimal_places": 2}}}}
        gathered = [{"step": "get_object", "object_type": "Transaction",
                     "result": {"t1": {"amount": Decimal("49.990000000")}}}]

        assert '"49.99"' in dumps_gathered(gathered, schema)

    def test_a_nested_field_uses_ITS_OWN_declaration(self):
        """THE SECOND CONTROL THAT PROVED NOTHING. Dropping the
        get_object branch still passed, because the generic dict path
        renders nested values anyway -- just without reaching each
        field's declaration. This is the case that separates them: the
        same value, padded because the FIELD says two places."""
        schema = {"Transaction": {"fields": {"amount": {"decimal_places": 2}}}}
        gathered = [{"step": "get_object", "object_type": "Transaction",
                     "result": {"t1": {"amount": Decimal("49.9")}}}]

        assert '"49.90"' in dumps_gathered(gathered, schema)

    def test_a_lone_unknown_type_cannot_crash_the_agent(self):
        """The last resort. Every type the ontology serves is handled
        above; this is so that ADDING one cannot take a running agent
        down while somebody teaches the renderer about it."""
        class Odd:
            def __str__(self):
                return "odd"

        assert "odd" in dumps_gathered([{"step": "x", "result": Odd()}])
