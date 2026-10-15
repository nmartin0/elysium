"""An answer resting on inferred values says so, and code makes sure (R63).

"The agent reads evaluation results, code enforces them." The model is
told which values in its data were inferred and how the rules scored;
whatever it writes, code appends a note naming them.
"""

import pytest

from core.enrichment_recipes import EnrichmentRecipeStore
from core.llm.inferred_values import InferredField, inferred_fields, inferred_in
from core.llm.synthesis_prompt import synthesize_insight
from core.ontology.enriched_fields import declaration_hash, enrichment_of

SCHEMA = {"SupportTicket": {"fields": {
    "subject": {"type": "data"},
    "topic": {"type": "data", "enrich": {"from": ["subject"],
                                         "instruction": "What the ticket is about.",
                                         "choices": ["billing", "technical", "refund"]}}}}}
TOPIC = InferredField("SupportTicket", "topic", "inferred from subject", agreed=35, covered=40)
INFERRED = {("SupportTicket", "topic"): TOPIC}


class Recorder:
    """Answers as told, and keeps what it was shown."""

    def __init__(self, answer):
        self.answer, self.seen = answer, None

    def chat(self, system_prompt, user_message, json_mode=False, temperature=None, *,
             deadline=None, usage=None, cancel=None):
        self.seen = user_message
        return self.answer


def read_topic(value="billing"):
    return [{"step": "get_field", "object_type": "SupportTicket", "object_id": "t1",
             "field_name": "topic", "result": value}]


class TestCodeEnforcesIt:
    def test_the_note_is_appended_whatever_the_model_wrote(self):
        answer = synthesize_insight(Recorder("Ticket t1 is about billing."), "What is t1 about?",
                                    read_topic(), inferred=INFERRED)

        assert answer.startswith("Ticket t1 is about billing.")
        assert "Inferred, not recorded" in answer
        assert "SupportTicket.topic was chosen by rules a person approved" in answer
        assert "agreed with the model's own answers on 35 of 40 held-out records" in answer

    def test_an_answer_with_no_inferred_data_has_no_note(self):
        records = [{"step": "get_field", "object_type": "SupportTicket", "object_id": "t1",
                    "field_name": "subject", "result": "Refund please"}]

        answer = synthesize_insight(Recorder("It asks for a refund."), "Subject of t1?",
                                    records, inferred=INFERRED)

        assert answer == "It asks for a refund."

    def test_a_withheld_answer_gets_no_note(self):
        """The note is appended after the checks; an answer they withhold
        is replaced, and a note about its data would describe nothing."""
        answer = synthesize_insight(Recorder("It cost $7,412.00."), "What is t1 about?",
                                    read_topic(), inferred=INFERRED)

        assert "withheld" in answer and "Inferred, not recorded" not in answer


class TestTheModelReadsIt:
    def test_the_model_is_told_which_values_are_inferred_and_how_they_scored(self):
        model = Recorder("About billing.")

        synthesize_insight(model, "What is t1 about?", read_topic(), inferred=INFERRED)

        assert "INFERRED, not recorded" in model.seen
        assert "SupportTicket.topic: inferred from subject" in model.seen
        assert "35 of 40" in model.seen

    def test_quoting_the_score_is_not_an_invented_figure(self):
        """The figures check withholds numbers that are in no record. The
        score is in none -- we told the model it -- so a correct answer
        quoting it was withheld until the told text counted as data."""
        answer = synthesize_insight(
            Recorder("Billing, though the rules agreed on 35 of 40 held-out records."),
            "What is t1 about?", read_topic(), inferred=INFERRED)

        assert "withheld" not in answer


class TestWhatCountsAsInferredData:
    @pytest.mark.parametrize("item", [
        {"step": "get_field", "field_name": "topic", "result": "billing"},
        {"step": "get_object", "field_names": ["topic"], "result": {"t1": {"topic": "x"}}},
        {"step": "get_object", "result": {"t1": {"subject": "s", "topic": "x"}}},
        {"step": "get_object", "result": {"subject": "s", "topic": "x"}},
        # SELECTED BY the inference: the ids are only as good as it is.
        {"step": "search_object", "filter": {"topic": "billing"}, "result": ["t1"]},
        {"step": "aggregate_object", "aggregate": "count", "group_by": "topic",
         "result": {"billing": 3}},
    ])
    def test_every_route_by_which_an_inference_reaches_the_data(self, item):
        assert inferred_in([{"object_type": "SupportTicket", **item}], INFERRED) == [TOPIC]

    def test_the_same_field_on_another_type_is_not_it(self):
        assert inferred_in([{"object_type": "Order", "step": "get_field",
                             "field_name": "topic", "result": "x"}], INFERRED) == []


class TestTheScoreComesFromTheApprovedRecipe:
    def _store(self, tmp_path, approve=True):
        store = EnrichmentRecipeStore(tmp_path / "recipes.db")
        enrichment = enrichment_of(SCHEMA["SupportTicket"]["fields"]["topic"])
        recipe = store.propose(
            "SupportTicket", "topic", declaration_hash("SupportTicket", "topic", enrichment),
            rules=[], evaluation={"held_out": {"rows": 50, "covered": 40, "agreed": 35}},
            provenance={})
        if approve:
            store.decide(recipe, True, "approver")
        return store

    def test_an_approved_recipe_supplies_it(self, tmp_path):
        found = inferred_fields(SCHEMA, self._store(tmp_path))

        assert found[("SupportTicket", "topic")] == TOPIC

    def test_a_proposed_recipe_does_not(self, tmp_path):
        found = inferred_fields(SCHEMA, self._store(tmp_path, approve=False))

        assert found[("SupportTicket", "topic")].agreed is None

    def test_with_no_store_the_field_is_still_named(self):
        field = inferred_fields(SCHEMA)[("SupportTicket", "topic")]

        assert field.score() == "no held-out score was recorded when they were approved"
