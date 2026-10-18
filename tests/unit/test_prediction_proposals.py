"""Proposing and approving a predicted field (R48): the store, what may
be approved, and the field a score is broken down by."""

import pytest

from core.ontology.predicted_fields import check_group_by, prediction_of
from core.prediction_proposals import PredictionProposalStore
from core.predictions import refusal
from tests.unit.test_predictions import _types

GOOD = {"skill": 0.42, "groups": [{"value": "US", "records": 80, "score": 0.9, "skill": 0.5}],
        "group_by": "region"}


class TestWhatMayBeApproved:
    def test_a_model_that_beats_the_naive_guess_with_a_breakdown_may_be(self):
        assert refusal(GOOD) is None

    @pytest.mark.parametrize("skill", [0.0, -0.3])
    def test_no_better_than_guessing_may_not_be(self, skill):
        assert "no better than the naive guess" in refusal({**GOOD, "skill": skill})

    def test_without_a_breakdown_by_group_it_may_not_be(self):
        assert "broken down by group" in refusal({**GOOD, "groups": None})
        assert "broken down by group" in refusal({**GOOD, "groups": []})

    def test_a_measurement_with_no_skill_may_not_be(self):
        assert refusal({"groups": GOOD["groups"]}) is not None


class TestTheGroupField:
    def _check(self, group_by):
        type_def = _types()["Customer"]
        fields = type_def["fields"]
        check_group_by("Customer", type_def, "risk", prediction_of(fields["risk"], fields),
                       group_by)

    def test_an_input_or_another_plain_field_is_allowed(self):
        self._check("region")
        self._check("joined")

    @pytest.mark.parametrize("group_by, why", [
        ("nope", "not a field"),
        ("customer_id", "the id"),
        ("risk", "the predicted field"),
        ("churned", "the answer"),
        ("email", "classified"),
        ("label", "computed or a link"),
        ("account", "computed or a link"),
    ])
    def test_a_field_that_cannot_group_fairly_is_refused(self, group_by, why):
        with pytest.raises(ValueError, match=why):
            self._check(group_by)


class TestTheStore:
    def _store(self, tmp_path):
        return PredictionProposalStore(tmp_path / "prediction_proposals.db")

    def test_only_an_approved_proposal_for_the_current_question_is_trained(self, tmp_path):
        store = self._store(tmp_path)
        waiting = store.propose("Customer", "risk", "h1", "us-west", GOOD, {})
        assert store.approved("Customer", "risk", "h1") == []
        store.decide(waiting, approve=True, by="ops")
        assert [p.proposal_id for p in store.approved("Customer", "risk", "h1")] == [waiting]
        assert store.approved("Customer", "risk", "h2") == [], "a changed question"

    def test_one_approval_per_compartment_and_a_new_one_supersedes(self, tmp_path):
        store = self._store(tmp_path)
        west = store.propose("Customer", "risk", "h1", "us-west", GOOD, {})
        east = store.propose("Customer", "risk", "h1", "us-east", GOOD, {})
        store.decide(west, approve=True, by="ops")
        store.decide(east, approve=True, by="ops")
        assert {p.compartment for p in store.approved("Customer", "risk", "h1")} == {
            "us-west", "us-east"}
        again = store.propose("Customer", "risk", "h1", "us-west", GOOD, {})
        store.decide(again, approve=True, by="ops")
        assert store.get(west).status == "superseded"
        assert store.get(east).status == "approved", "another compartment is untouched"
        assert {p.proposal_id for p in store.approved("Customer", "risk", "h1")} == {again, east}

    def test_no_compartment_and_an_empty_one_are_different(self, tmp_path):
        store = self._store(tmp_path)
        none = store.propose("Customer", "risk", "h1", None, GOOD, {})
        empty = store.propose("Customer", "risk", "h1", "", GOOD, {})
        store.decide(none, approve=True, by="ops")
        store.decide(empty, approve=True, by="ops")
        assert sorted(map(repr, (p.compartment for p in store.approved("Customer", "risk", "h1")))
                      ) == ["''", "None"]

    def test_a_decided_proposal_is_not_decided_again(self, tmp_path):
        store = self._store(tmp_path)
        proposal = store.propose("Customer", "risk", "h1", None, GOOD, {})
        store.decide(proposal, approve=False, by="ops")
        assert store.decide(proposal, approve=True, by="ops") is None
        assert store.approved("Customer", "risk", "h1") == []

    def test_an_unreadable_store_approves_nothing(self, tmp_path):
        (tmp_path / "prediction_proposals.db").write_text("not a database")
        assert self._store(tmp_path).approved("Customer", "risk", "h1") == []
