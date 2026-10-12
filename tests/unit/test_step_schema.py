"""The step vocabulary as a JSON Schema (AR-5): what it admits, what it
cannot express, and that it reaches the model server.

THE REJECTIONS ARE THE BENCH'S OWN STEPS, verbatim from its logs on the
deployment's model (BLOCKING 12). Each was emitted, refused by the
loop, and cost a hop. Under the schema none of them can be emitted.

THE ACCEPTANCES ARE THE CONTROL. A grammar that admitted nothing would
pass every rejection test and stop the agent cold -- and the symptom,
no answers, would look like the model's fault.

jsonschema validates here; llama.cpp compiles the same schema into a
grammar on the server. Agreeing with the first is evidence for, not
proof of, the second -- which is why the bench has a --constrain arm.
"""

import jsonschema
import pytest

from core.llm.step_schema import step_schema

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "fields": {
            "name": {"type": "data"},
            "region": {"type": "data"},
            "transactions": {"type": "link", "target": "Transaction", "cardinality": "many"},
        },
    },
    "Transaction": {
        "id_field": "transaction_id",
        "fields": {
            "amount": {"type": "data", "data_type": "number"},
            "category": {"type": "data"},
            "transaction_date": {"type": "data", "data_type": "date"},
            "customer_id": {"type": "link", "target": "Customer", "cardinality": "one"},
        },
    },
}


class _Tool:
    def __init__(self, name):
        self.name = name


def _admits(step, schema=SCHEMA, tools=(), writes=False, actions=None):
    try:
        jsonschema.validate(step, step_schema(schema, list(tools), writes, actions or {}))
    except jsonschema.ValidationError:
        return False
    return True


class TestWhatTheBenchsModelSentCannotBeSent:
    @pytest.mark.parametrize("step", [
        # count_by_aggregate, three trials of three
        {"step": "get_object", "object_type": "Transaction", "object_ids": ["1", "2"],
         "field_names": ["count"]},
        {"step": "get_field", "object_type": "Transaction", "object_id": "1", "field_name": "count"},
        # its next move, once "count" was refused
        {"step": "get_object", "object_type": "Transaction", "object_ids": ["1", "2"],
         "field_names": ["transaction_id"]},
        # the wildcard that started _reject_unknown_fields
        {"step": "get_object", "object_type": "Transaction", "object_ids": [1],
         "field_names": ["*"]},
        # plan mode's "list of values in a filter that takes one"
        {"step": "search_object", "object_type": "Transaction",
         "filter": {"customer_id": ["cust_001", "cust_002"]}},
        # the invented step name
        {"step": "get_transaction_amount", "object_type": "Transaction"},
    ], ids=["count-field", "count-get_field", "id-field", "wildcard", "list-filter", "invented-step"])
    def test_refused_by_the_grammar(self, step):
        assert not _admits(step)

    def test_a_date_that_is_not_iso_is_refused(self):
        """The CONSTRAINED bench run's own step: the grammar admitted
        it, and the executor refused it a hop later."""
        assert not _admits({"step": "search_object", "object_type": "Transaction",
                            "filter": {"transaction_date": "2"}})

    def test_a_link_is_not_something_to_group_by(self):
        """The constrained run's other admitted-then-refused step."""
        assert not _admits({"step": "aggregate_object", "object_type": "Transaction",
                            "aggregate": "count", "filter": {}, "field_name": "transaction_date",
                            "group_by": "customer_id"})

    def test_a_field_of_another_type_is_refused(self):
        """Customer's `name` asked of a Transaction -- valid alone,
        wrong in combination, which is why each type is its own branch."""
        assert not _admits({"step": "get_field", "object_type": "Transaction",
                            "object_id": 1, "field_name": "name"})

    def test_a_reverse_link_is_not_a_filter(self):
        """Not searchable (is_searchable_field), so not in the filter."""
        assert not _admits({"step": "search_object", "object_type": "Customer",
                            "filter": {"transactions": "1"}})

    def test_a_type_the_caller_cannot_see_does_not_exist(self):
        assert not _admits({"step": "get_field", "object_type": "Account",
                            "object_id": "a", "field_name": "balance"})


class TestWhatTheBenchsPassingRunsSentIsAdmitted:
    @pytest.mark.parametrize("step", [
        {"step": "search_object", "object_type": "Customer", "filter": {"name": "Ada Okafor"}},
        {"step": "get_field", "object_type": "Customer", "object_id": "cust_001",
         "field_name": "transactions"},
        {"step": "search_object", "object_type": "Transaction", "filter": {"customer_id": "cust_001"}},
        {"step": "get_field", "object_type": "Transaction", "object_id": "1", "field_name": "category"},
        {"step": "get_object", "object_type": "Transaction", "object_ids": [1, 2],
         "field_names": ["amount", "category"]},
        {"step": "aggregate_object", "object_type": "Transaction",
         "filter": {"customer_id": "cust_001"}, "aggregate": "count"},
        {"step": "aggregate_object", "object_type": "Transaction", "filter": {},
         "aggregate": "max", "field_name": "amount", "group_by": "category"},
        {"step": "search_object", "object_type": "Transaction",
         "filter": {"transaction_date": "2026-05-14"}},
        {"step": "search_around", "object_type": "Customer", "filter": {"region": "us-west"},
         "link_field": "transactions"},
        {"step": "finish"},
    ])
    def test_admitted(self, step):
        assert _admits(step)


class TestItOffersOnlyWhatThePromptOffers:
    def test_a_tool_is_callable_only_when_enabled(self):
        step = {"step": "use_tool", "tool_name": "calculator", "args": {}}

        assert _admits(step, tools=[_Tool("calculator")])
        assert not _admits(step)

    def test_an_action_only_when_writes_are_on_and_it_is_visible(self):
        step = {"step": "propose_action", "action_type": "UpdateName", "parameters": {}}

        assert _admits(step, writes=True, actions={"UpdateName": {}})
        assert not _admits(step, writes=False, actions={"UpdateName": {}})
        assert not _admits(step, writes=True, actions={"Other": {}})


class TestItReachesTheServer:
    def test_ollama_sends_the_schema_as_format(self):
        """Built the way the deployment builds it, and nothing swallowed:
        a first version constructed the adapter by hand inside a try/
        except, and went on passing only until the adapter grew an
        attribute it lacked."""
        from unittest.mock import Mock, patch

        from adapters.ollama_adapter import OllamaAdapter

        response = Mock()
        response.json.return_value = {"message": {"content": "{}"}}
        response.raise_for_status.return_value = None
        schema = {"anyOf": [{"type": "object"}]}
        with patch("adapters.ollama_adapter.requests.post", return_value=response) as post:
            OllamaAdapter("m", {"base_url": "http://x"}).chat("s", "u", json_mode=schema)

        assert post.call_args.kwargs["json"]["format"] == schema

    def test_next_step_passes_a_schema_only_when_constrained(self):
        from core.llm.agent_step_prompt import next_step

        seen = []

        class Client:
            max_concurrent_requests = 1

            def chat(self, system_prompt, user_message, json_mode=False, temperature=None,
                     *, deadline=None, usage=None):
                seen.append(json_mode)
                return '{"step": "finish"}'

        for constrain in (False, True):
            next_step(Client(), "q", SCHEMA, [], [], False, {}, constrain=constrain)

        assert seen[0] is True
        assert isinstance(seen[1], dict) and "anyOf" in seen[1]


class TestThePlanSchema:
    """The bench's plan-mode failures, 2026-10-11, verbatim in shape."""

    def _admits(self, plan, max_steps=8):
        from core.llm.step_schema import plan_schema

        try:
            jsonschema.validate(plan, plan_schema(SCHEMA, [], False, {}, max_steps))
        except jsonschema.ValidationError:
            return False
        return True

    FIND = {"id": "a", "step": "search_object", "object_type": "Customer",
            "filter": {"name": "Ada Okafor"}}
    LINK = {"id": "b", "step": "get_field", "object_type": "Customer", "object_id": "$a",
            "field_name": "transactions"}

    def test_a_correct_plan_with_handles_is_admitted(self):
        """THE CONTROL: dependent_choice's own intended chain."""
        assert self._admits({"plan": [
            {"id": "a", "step": "aggregate_object", "object_type": "Transaction",
             "filter": {"customer_id": "cust_001"}, "aggregate": "max", "field_name": "amount"},
            {"id": "b", "step": "search_object", "object_type": "Transaction",
             "filter": {"amount": "$a"}},
            {"id": "c", "step": "get_field", "object_type": "Transaction", "object_id": "$b",
             "field_name": "category"},
        ]})

    def test_a_bare_handle_stands_for_a_list(self):
        assert self._admits({"plan": [self.FIND, self.LINK, {
            "id": "c", "step": "get_object", "object_type": "Transaction",
            "object_ids": "$b", "field_names": ["amount"]}]})

    def test_a_wrapped_handle_is_refused(self):
        """`["$b"]` -- the bench's second plan-mode mistake."""
        assert not self._admits({"plan": [self.FIND, self.LINK, {
            "id": "c", "step": "get_object", "object_type": "Transaction",
            "object_ids": ["$b"], "field_names": ["amount"]}]})

    def test_written_out_ids_are_still_admitted(self):
        """THE CONTROL for the test above."""
        assert self._admits({"plan": [self.FIND, {
            "id": "c", "step": "get_object", "object_type": "Transaction",
            "object_ids": [1, "2"], "field_names": ["amount"]}]})

    def test_a_list_in_a_filter_is_refused(self):
        assert not self._admits({"plan": [
            {"id": "a", "step": "search_object", "object_type": "Transaction",
             "filter": {"customer_id": ["cust_001"]}}]})

    def test_a_plan_longer_than_the_hop_limit_is_refused(self):
        steps = [dict(self.FIND, id=f"s{i}") for i in range(9)]

        assert self._admits({"plan": steps[:8]})
        assert not self._admits({"plan": steps})

    def test_a_step_without_an_id_is_refused(self):
        step = {key: value for key, value in self.FIND.items() if key != "id"}

        assert not self._admits({"plan": [step]})

    def test_finish_is_not_a_plan_step(self):
        assert not self._admits({"plan": [{"id": "a", "step": "finish"}]})
