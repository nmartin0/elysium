"""Predicted fields (R48): the declaration, and learning and measuring --
on synthetic records whose true pattern is known, so a score that
passes is about the model and not about luck."""

import datetime
import random

import pytest

from core.ontology.predicted_fields import (
    declaration_hash,
    fill_predicted_types,
    predicted_fields,
    prediction_of,
    validate_predicted_fields,
)
from core.predictions import MIN_GROUP, MIN_KNOWN, NotLearnable, train


def _types(**predict):
    field = {"predict": predict or {"of": "churned", "from": ["plan", "tenure", "region"],
                                    "chance_of": "yes"}}
    return {"Customer": {"id_field": "customer_id", "fields": {
        "customer_id": {"type": "data"},
        "plan": {"type": "data"},
        "tenure": {"type": "data", "data_type": "integer"},
        "region": {"type": "data"},
        "joined": {"type": "data", "data_type": "date"},
        "spend": {"type": "data", "data_type": "decimal"},
        "churned": {"type": "data"},
        "email": {"type": "data", "classification": ["pii"]},
        "health": {"type": "data", "classification": ["special"]},
        "account": {"type": "link", "target": "Account"},
        "label": {"derived": {"concat": ["plan", "churned"]}},
        "risk": field,
    }}}


DATA_TYPES = {"plan": "string", "tenure": "integer", "region": "string", "joined": "date",
              "spend": "decimal", "churned": "string"}


class TestTheDeclaration:
    @pytest.mark.parametrize("predict, kind, data_type", [
        ({"of": "churned", "from": ["plan"], "chance_of": "yes"}, "chance", "number"),
        ({"of": "churned", "from": ["plan"]}, "class", "string"),
        ({"of": "spend", "from": ["plan", "tenure"]}, "number", "number"),
    ])
    def test_the_answers_type_decides_the_shape(self, predict, kind, data_type):
        types = _types(**predict)
        validate_predicted_fields(types)
        fill_predicted_types(types)
        fields = types["Customer"]["fields"]
        prediction = prediction_of(fields["risk"], fields)
        assert (prediction.kind, fields["risk"]["data_type"]) == (kind, data_type)
        assert prediction.describe().startswith("predicted from ")

    @pytest.mark.parametrize("predict, why", [
        ({"of": "nope", "from": ["plan"]}, "not a field"),
        ({"of": "risk", "from": ["plan"]}, "cannot predict itself"),
        ({"of": "email", "from": ["plan"]}, "classified.*never learns about"),
        ({"of": "churned", "from": ["health"]}, "classified.*never learns from"),
        ({"of": "churned", "from": ["churned"]}, "is the answer itself"),
        ({"of": "churned", "from": ["customer_id"]}, "is the id"),
        ({"of": "churned", "from": ["label"]}, "computed from the answer"),
        ({"of": "churned", "from": ["account"]}, "is a link"),
        ({"of": "label", "from": ["plan"]}, "is computed or a link"),
        ({"of": "joined", "from": ["plan"]}, "learns text, yes/no or a number"),
        ({"of": "spend", "from": ["plan"], "chance_of": "1"}, "is a number"),
        ({"of": "churned", "from": []}, "1 to 20 fields"),
        ({"of": "churned", "from": ["plan", "plan"]}, "names a field twice"),
        ({"of": "churned", "from": ["plan"], "model": "gbm"}, "unknown key"),
    ])
    def test_a_prediction_that_could_not_be_learned_safely_is_refused(self, predict, why):
        with pytest.raises(ValueError, match=why):
            validate_predicted_fields(_types(**predict))

    def test_a_data_type_that_disagrees_with_the_shape_is_refused(self):
        types = _types(of="churned", **{"from": ["plan"]})
        types["Customer"]["fields"]["risk"]["data_type"] = "integer"
        with pytest.raises(ValueError, match="so it is string"):
            validate_predicted_fields(types)

    def test_the_hash_changes_with_the_question(self):
        fields = _types()["Customer"]["fields"]
        base = prediction_of(fields["risk"], fields)
        fields["risk"]["predict"]["from"] = ["plan"]
        assert declaration_hash("Customer", "risk", base) != declaration_hash(
            "Customer", "risk", prediction_of(fields["risk"], fields))

    def test_reading_a_prediction_needs_reading_the_answer_and_every_input(self):
        from core.ontology.derived_fields import gate_derived_grants

        types = _types()
        roles = {"no_answer": {"allowed_actions": frozenset({
                     "read:Customer", "read:Customer.risk", "read:Customer.plan",
                     "read:Customer.tenure", "read:Customer.region"})},
                 "all": {"allowed_actions": frozenset({
                     "read:Customer", "read:Customer.risk", "read:Customer.plan",
                     "read:Customer.tenure", "read:Customer.region", "read:Customer.churned"})}}
        gated = gate_derived_grants(roles, types)
        assert "read:Customer.risk" not in gated["no_answer"]["allowed_actions"]
        assert "discover:Customer.risk" in gated["no_answer"]["allowed_actions"]
        assert "read:Customer.risk" in gated["all"]["allowed_actions"]


def _customers(count=2_000, seed=1, weak_region="BR", leak=False):
    """Churn that truly depends on plan and tenure -- except in one small
    region, where it is a coin toss: the case an average hides."""
    rng = random.Random(seed)
    rows = []
    for index in range(count):
        plan = rng.choice(["basic", "pro", "team"])
        tenure = rng.randint(1, 60)
        region = weak_region if rng.random() < 0.1 else rng.choice(["US", "CA"])
        if region == weak_region:
            churned = rng.random() < 0.5
        else:
            churned = (plan == "basic" and tenure < 24) or rng.random() < 0.05
        row = {"customer_id": index, "plan": plan, "tenure": tenure, "region": region,
               "joined": datetime.date(2020, 1, 1) + datetime.timedelta(days=tenure * 30),
               "churned": "yes" if churned else "no"}
        if leak:
            row["cancelled"] = "y" if churned else None
        rows.append(row)
    return rows


def _prediction(**predict):
    fields = _types(**predict)["Customer"]["fields"]
    return prediction_of(fields["risk"], fields)


class TestLearning:
    def test_a_real_pattern_is_learned_and_beats_the_naive_guess(self):
        trained = train(_customers(), _prediction(), DATA_TYPES)
        evaluation = trained.evaluation
        assert evaluation["skill"] > 0.4
        assert evaluation["judged_on"] == pytest.approx(0.2 * evaluation["known"], abs=1)
        assert [item["field"] for item in evaluation["important"]][:2] == ["plan", "tenure"] \
            or [item["field"] for item in evaluation["important"]][:2] == ["tenure", "plan"]
        assert "warning" not in evaluation

    def test_noise_is_not_mistaken_for_a_pattern(self):
        rows = _customers()
        rng = random.Random(9)
        for row in rows:
            row["churned"] = rng.choice(["yes", "no"])
        assert train(rows, _prediction(), DATA_TYPES).evaluation["skill"] < 0.1

    def test_the_average_does_not_hide_a_group_it_fails(self):
        groups = {group["value"]: group for group in train(
            _customers(4_000), _prediction(), DATA_TYPES, group_by="region").evaluation["groups"]}
        assert groups["US"]["skill"] > 0.5 and groups["CA"]["skill"] > 0.5
        assert groups["BR"]["skill"] < 0.2, groups["BR"]

    def test_a_group_too_small_to_judge_shows_no_score(self):
        rows = _customers(1_000)
        for row in rows[:40]:
            row["region"] = "NZ"
        nz = next(group for group in train(rows, _prediction(), DATA_TYPES,
                                           group_by="region").evaluation["groups"]
                  if group["value"] == "NZ")
        assert nz["records"] < MIN_GROUP and nz["score"] is None and nz["skill"] is None

    def test_an_input_carrying_the_answer_is_said_to_be_too_good_to_be_true(self):
        rows = _customers(leak=True)
        types = dict(DATA_TYPES, cancelled="string")
        trained = train(rows, _prediction(of="churned", chance_of="yes",
                                          **{"from": ["plan", "cancelled"]}), types)
        assert "Too good to be true" in trained.evaluation["warning"]
        assert "'cancelled'" in trained.evaluation["warning"]

    def test_the_same_data_measures_and_predicts_the_same_every_time(self):
        rows = _customers()
        for row in rows[:100]:
            row["churned"] = None
        first, second = (train(rows, _prediction(), DATA_TYPES) for _ in range(2))
        assert first.evaluation == second.evaluation
        assert first.predict(rows) == second.predict(rows)


class TestPredicting:
    def _rows(self):
        rows = _customers()
        for row in rows[:50]:
            row["churned"] = None
        return rows

    def test_only_records_without_a_known_answer_are_predicted(self):
        rows = self._rows()
        values = train(rows, _prediction(), DATA_TYPES).predict(rows)
        assert all(value is not None for value in values[:50])
        assert all(value is None for value in values[50:])

    def test_a_chance_is_between_0_and_1_and_follows_the_pattern(self):
        rows = self._rows()
        rows[0].update(plan="basic", tenure=3, region="US")
        rows[1].update(plan="team", tenure=50, region="US")
        values = train(rows, _prediction(), DATA_TYPES).predict(rows)
        assert all(0 <= value <= 1 for value in values[:50])
        assert values[0] > 0.7 > 0.3 > values[1]

    def test_the_most_likely_answer_and_a_number_have_their_own_shapes(self):
        rows = self._rows()
        labels = train(rows, _prediction(of="churned", **{"from": ["plan", "tenure"]}),
                       DATA_TYPES).predict(rows)
        assert set(labels[:50]) <= {"yes", "no"}
        for row in rows:
            row["spend"] = None if row["churned"] is None else row["tenure"] * 10.0
        numbers = train(rows, _prediction(of="spend", **{"from": ["tenure"]}),
                        DATA_TYPES).predict(rows)
        assert all(isinstance(value, float) for value in numbers[:50])
        assert abs(numbers[0] - rows[0]["tenure"] * 10.0) < 60

    def test_a_value_never_seen_in_training_is_treated_as_missing(self):
        rows = self._rows()
        rows[0]["plan"] = "enterprise"
        assert train(rows, _prediction(), DATA_TYPES).predict(rows)[0] is not None


class TestNotEnough:
    def test_too_few_known_answers_is_said(self):
        rows = _customers(MIN_KNOWN - 1)
        with pytest.raises(NotLearnable, match=f"at least {MIN_KNOWN}"):
            train(rows, _prediction(), DATA_TYPES)

    def test_one_answer_for_everyone_is_nothing_to_learn(self):
        rows = _customers()
        for row in rows:
            row["churned"] = "no"
        with pytest.raises(NotLearnable, match="nothing to tell apart"):
            train(rows, _prediction(), DATA_TYPES)


def test_predicted_fields_lists_only_predicted_ones():
    assert list(predicted_fields(_types()["Customer"])) == ["risk"]


def test_the_schema_marks_a_prediction_as_predicted(test_db_path, test_schema):
    """Every reader of the visible schema can tell a prediction from a
    recorded fact -- the enrichment marker, in its own words."""
    import copy

    from core.intermediate_layer.auth import resolve_user_record
    from tests.conftest import author_book_mediator

    schema = copy.deepcopy(test_schema)
    schema["Book"]["fields"]["era"] = {"predict": {"of": "year", "from": ["title"]},
                                       "type": "data", "data_type": "string"}
    roles = {"reader": {"allowed_actions": frozenset({"read:Book", "read:Book.title",
                                                      "read:Book.year", "read:Book.era"})}}
    mediator = author_book_mediator(test_db_path, schema, roles)
    alice = resolve_user_record({"alice": {"org_id": "org-a", "role": "reader"}}, "alice",
                                "org_id")
    fields = mediator.visible_schema(alice)["Book"]["fields"]
    assert fields["era"]["inferred"] == "predicted from title"
    assert fields["title"]["inferred"] is None


class TestAComputedField:
    """A prediction has no stored value: nothing reads it from a source,
    writes it, or builds on it as though it were recorded."""

    def test_it_is_computed(self):
        from core.ontology.field_types import is_computed

        assert is_computed(_types()["Customer"]["fields"]["risk"])

    def test_the_sync_never_asks_the_source_for_it(self):
        from core.mirror.sync_targets import resolve_sync_targets

        types = _types()
        types["Customer"]["fields"].pop("account")
        types["Customer"]["fields"].pop("label")
        types["Customer"]["storage"] = {"silo": "s", "table": "customers",
                                        "id_column": "customer_id"}
        (target,) = resolve_sync_targets({"object_types": types})
        assert "risk" not in target.columns and "churned" in target.columns

    def test_meaning_is_never_embedded_from_it(self):
        from core.ontology.semantic_search import validate_semantic_search

        types = _types()
        types["Customer"]["semantic_search"] = {"from": ["risk"]}
        with pytest.raises(ValueError, match="is computed"):
            validate_semantic_search(types, "nomic-embed-text")
