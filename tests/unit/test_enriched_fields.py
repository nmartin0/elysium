"""Fields filled in by approved rules (R41, R42, R38): the declaration,
the rule language a model may write in, and what gold does with it."""

import pyarrow as pa
import pytest

from core.enrichment_recipes import EnrichmentRecipeStore
from core.mirror.enrichment import with_approved_recipes
from core.mirror.gold_arrow import APPROVED_RULES, with_derived
from core.ontology.derived_fields import gate_derived_grants
from core.ontology.enriched_fields import (
    RuleError,
    apply_recipe,
    apply_rules,
    check_recipe,
    check_rules,
    declaration_hash,
    describe_recipe,
    enrichment_of,
    fill_enriched_types,
    validate_enriched_fields,
)


def _types(**topic):
    field = {"enrich": {"from": ["subject"], "instruction": "What the ticket is about.",
                        "choices": ["billing", "technical", "refund"]}}
    field.update(topic)
    return {"SupportTicket": {"fields": {
        "subject": {"type": "data"},
        "body": {"type": "data", "data_type": "string"},
        "amount": {"type": "data", "data_type": "decimal"},
        "email": {"type": "data", "classification": ["pii"]},
        "customer": {"type": "link", "target": "Customer"},
        "total": {"derived": {"concat": ["subject", "body"]}},
        "topic": field,
    }}}


def _enrich(**overrides):
    declared = {"from": ["subject"], "instruction": "What the ticket is about.",
                "choices": ["billing", "technical", "refund"]}
    declared.update(overrides)
    return _types(enrich=declared)


class TestTheDeclaration:
    def test_a_good_one_loads_and_is_typed_as_text(self):
        types = _types()
        validate_enriched_fields(types)
        fill_enriched_types(types)
        assert types["SupportTicket"]["fields"]["topic"]["data_type"] == "string"
        assert enrichment_of(types["SupportTicket"]["fields"]["topic"]).describe() == \
            "inferred from subject"

    def test_a_classified_input_is_refused_never_sent(self):
        """The owner's call, 15 October: a classified value never reaches
        a model until D3 says data may leave the VM at all."""
        with pytest.raises(ValueError, match="classified.*never sent to a model"):
            validate_enriched_fields(_enrich(**{"from": ["subject", "email"]}))

    @pytest.mark.parametrize("inputs, why", [
        (["customer"], "is a link"),
        (["total"], "computed itself"),
        (["amount"], "inputs are text"),
        (["nope"], "does not have"),
        (["topic"], "from itself"),
        ([], "names the fields"),
    ])
    def test_an_input_it_cannot_read_as_text_is_refused(self, inputs, why):
        with pytest.raises(ValueError, match=why):
            validate_enriched_fields(_enrich(**{"from": inputs}))

    @pytest.mark.parametrize("overrides, why", [
        ({"choices": ["only"]}, "between 2 and"),
        ({"choices": ["Billing", "billing"]}, "differ only in case"),
        ({"instruction": "  "}, "needs an instruction"),
        ({"instruction": "x" * 501}, "at most 500"),
        ({"temperature": 0}, "unknown key"),
    ])
    def test_a_question_it_could_not_answer_is_refused(self, overrides, why):
        with pytest.raises(ValueError, match=why):
            validate_enriched_fields(_enrich(**overrides))

    def test_it_has_no_stored_value_to_describe(self):
        with pytest.raises(ValueError, match="no stored value"):
            validate_enriched_fields(_types(storage="primary"))
        with pytest.raises(ValueError, match="is a string"):
            validate_enriched_fields(_types(data_type="integer"))

    def test_an_approval_is_of_one_exact_question(self):
        a = enrichment_of(_types()["SupportTicket"]["fields"]["topic"])
        b = enrichment_of(_enrich(instruction="What it is about, briefly.")
                          ["SupportTicket"]["fields"]["topic"])
        assert declaration_hash("SupportTicket", "topic", a) != \
            declaration_hash("SupportTicket", "topic", b)


ENRICHMENT = enrichment_of(_types()["SupportTicket"]["fields"]["topic"])


class TestTheRuleLanguage:
    def test_rules_are_rebuilt_from_what_was_checked(self):
        """An extra key a model adds -- here an attempt to smuggle code --
        never reaches storage."""
        checked = check_rules([{"when": [{"field": "subject", "contains_any": ["Refund", "money back"],
                                          "regex": ".*"}],
                                "then": "REFUND", "python": "import os"}], ENRICHMENT)
        assert checked == [{"when": [{"field": "subject", "contains_any": ["money back", "refund"]}],
                            "then": "refund"}]

    @pytest.mark.parametrize("rules, why", [
        ([], "non-empty"),
        ([{"when": [{"field": "subject", "contains_any": ["x"]}], "then": "angry"}], "not one of the choices"),
        ([{"when": [{"field": "body", "contains_any": ["x"]}], "then": "billing"}], "not an input"),
        ([{"when": [], "then": "billing"}], "conditions"),
        ([{"when": [{"field": "subject", "contains_any": ["!!!"]}], "then": "billing"}], "word or phrase"),
        ([{"when": [{"field": "subject", "contains_any": "refund"}], "then": "refund"}], "contains_any"),
        ("rules", "non-empty list"),
    ])
    def test_anything_else_is_refused(self, rules, why):
        with pytest.raises(RuleError, match=why):
            check_rules(rules, ENRICHMENT)

    RULES = check_rules([
        {"when": [{"field": "subject", "contains_any": ["refund"]}], "then": "refund"},
        {"when": [{"field": "subject", "contains_any": ["invoice", "billing address"]}], "then": "billing"},
        {"when": [{"field": "subject", "contains_any": ["error", "login"]}], "then": "technical"},
    ], ENRICHMENT)

    @pytest.mark.parametrize("subject, expected", [
        ("Requesting a REFUND for hardware", ("refund", 1)),
        ("Cannot update billing address", ("billing", 2)),
        ("Login page returns a 500 error", ("technical", 3)),
        # WHOLE WORDS: "errors" is not "error", and "billing" alone is
        # not the phrase "billing address".
        ("So many errors", (None, None)),
        ("A billing question", (None, None)),
        # FIRST RULE WINS: a refund about a login is a refund.
        ("Refund after login failure", ("refund", 1)),
        # NO RULE HOLDS: empty, never a guess (R52).
        ("Hello there", (None, None)),
        (None, (None, None)),
    ])
    def test_the_first_rule_that_holds_gives_the_value(self, subject, expected):
        assert apply_rules(self.RULES, {"subject": subject}) == expected


class TestGold:
    def _table(self):
        return pa.table({"ticket_id": [1, 2, 3],
                         "subject": ["Refund please", "Login error", "Hello"],
                         "topic": pa.array([None, None, None], type=pa.string())})

    def test_approved_rules_fill_the_column_and_nothing_else_does(self):
        type_def = _types()["SupportTicket"]
        assert with_derived(self._table(), type_def).column("topic").to_pylist() == [None, None, None]

        type_def["fields"]["topic"][APPROVED_RULES] = TestTheRuleLanguage.RULES
        assert with_derived(self._table(), type_def).column("topic").to_pylist() == \
            ["refund", "technical", None]


class TestTheStore:
    def test_only_an_approved_recipe_for_the_current_question_reaches_gold(self, tmp_path):
        store = EnrichmentRecipeStore(tmp_path / "recipes.db")
        types = _types()
        validate_enriched_fields(types)
        type_def = types["SupportTicket"]
        digest = declaration_hash("SupportTicket", "topic", ENRICHMENT)

        recipe = store.propose("SupportTicket", "topic", digest, TestTheRuleLanguage.RULES,
                               {"sample": 3}, {"model": "test"})
        # PROPOSED IS NOT APPROVED.
        assert APPROVED_RULES not in with_approved_recipes("SupportTicket", type_def, store)["fields"]["topic"]

        store.decide(recipe, approve=True, by="ops")
        assert with_approved_recipes("SupportTicket", type_def, store)["fields"]["topic"][APPROVED_RULES] \
            == TestTheRuleLanguage.RULES

        # THE QUESTION CHANGES: the approval no longer applies.
        changed = _enrich(instruction="Something else entirely.")
        validate_enriched_fields(changed)
        assert APPROVED_RULES not in with_approved_recipes(
            "SupportTicket", changed["SupportTicket"], store)["fields"]["topic"]

    def test_approving_another_supersedes_and_a_decision_is_made_once(self, tmp_path):
        store = EnrichmentRecipeStore(tmp_path / "recipes.db")
        first = store.propose("T", "f", "h", [1], {}, {})
        second = store.propose("T", "f", "h", [2], {}, {})
        store.decide(first, approve=True, by="ops")
        store.decide(second, approve=True, by="ops")

        assert store.get(first).status == "superseded"
        assert store.approved_rules("T", "f", "h") == [2]
        assert store.decide(first, approve=True, by="ops") is None

    def test_a_rejected_recipe_publishes_nothing(self, tmp_path):
        store = EnrichmentRecipeStore(tmp_path / "recipes.db")
        store.decide(store.propose("T", "f", "h", [1], {}, {}), approve=False, by="ops")
        assert store.approved_rules("T", "f", "h") is None

    def test_a_type_with_nothing_enriched_is_handed_back_untouched(self, tmp_path):
        type_def = {"fields": {"a": {"type": "data"}}}
        assert with_approved_recipes("T", type_def, EnrichmentRecipeStore(tmp_path / "r.db")) is type_def


def test_reading_an_inference_needs_reading_what_it_was_inferred_from():
    """An inferred topic summarises the subject, as a total summarises a
    price -- so it is withheld from a role refused the subject."""
    types = _types()
    roles = {"agent": {"allowed_actions": frozenset({"read:SupportTicket.topic"})},
             "lead": {"allowed_actions": frozenset({"read:SupportTicket.topic",
                                                    "read:SupportTicket.subject"})}}
    gated = gate_derived_grants(roles, types)
    assert "read:SupportTicket.topic" not in gated["agent"]["allowed_actions"]
    assert "discover:SupportTicket.topic" in gated["agent"]["allowed_actions"]
    assert "read:SupportTicket.topic" in gated["lead"]["allowed_actions"]


class TestSeveralRuleSetsVote:
    """A combined recipe (EVAPORATE-Code+): rule sets that vote, each by
    its weight. Still data -- checked like one set, run by this module."""

    ENRICHMENT = enrichment_of(_types()["SupportTicket"]["fields"]["topic"])
    REFUND = [{"when": [{"field": "subject", "contains_any": ["refund"]}], "then": "refund"}]
    BILLING = [{"when": [{"field": "subject", "contains_any": ["refund", "invoice"]}], "then": "billing"}]
    TECHNICAL = [{"when": [{"field": "subject", "contains_any": ["refund"]}], "then": "technical"}]

    def _vote(self, *members):
        return {"combine": "weighted_vote",
                "members": [{"weight": weight, "rules": rules} for weight, rules in members]}

    def test_the_heavier_side_wins_and_lone_answers_stand(self):
        recipe = check_recipe(self._vote((2.0, self.REFUND), (1.5, self.BILLING)), self.ENRICHMENT)
        assert apply_recipe(recipe, {"subject": "Refund please"}) == "refund"
        # ONLY ONE MEMBER ANSWERS: its answer is the vote.
        assert apply_recipe(recipe, {"subject": "Invoice wrong"}) == "billing"
        assert apply_recipe(recipe, {"subject": "Hello"}) is None

    def test_two_lighter_sets_agreeing_outvote_one_heavier(self):
        recipe = check_recipe(self._vote((2.0, self.REFUND), (1.5, self.BILLING), (1.0, self.BILLING)),
                              self.ENRICHMENT)
        assert apply_recipe(recipe, {"subject": "Refund please"}) == "billing"

    def test_a_tie_is_left_empty_rather_than_guessed(self):
        recipe = check_recipe(self._vote((1.0, self.REFUND), (1.0, self.TECHNICAL)), self.ENRICHMENT)
        assert apply_recipe(recipe, {"subject": "Refund please"}) is None

    def test_one_rule_set_is_still_one_rule_set(self):
        recipe = check_recipe(self.REFUND, self.ENRICHMENT)
        assert recipe == check_rules(self.REFUND, self.ENRICHMENT)
        assert apply_recipe(recipe, {"subject": "refund"}) == "refund"
        assert describe_recipe(recipe) == [{"weight": None, "rules": ["If subject mentions 'refund': refund"]}]

    def test_every_member_is_checked_as_a_rule_set_is(self):
        bad = [{"when": [{"field": "email", "contains_any": ["x"]}], "then": "refund"}]
        with pytest.raises(RuleError, match="member 2"):
            check_recipe(self._vote((1.0, self.REFUND), (1.0, bad)), self.ENRICHMENT)

    @pytest.mark.parametrize("recipe, says", [
        ({"combine": "weighted_vote", "members": [{"weight": 1.0, "rules": REFUND}]}, "2 to 5 members"),
        ({"combine": "weighted_vote", "members": [{"weight": 1.0, "rules": REFUND}] * 6}, "2 to 5 members"),
        ({"combine": "majority", "members": []}, "weighted_vote"),
        ({"combine": "weighted_vote", "members": [], "code": "print()"}, "weighted_vote"),
        ({"combine": "weighted_vote", "members": [{"weight": 0, "rules": REFUND}] * 2}, "above 0"),
        ({"combine": "weighted_vote", "members": [{"weight": 11, "rules": REFUND}] * 2}, "at most 10"),
        ({"combine": "weighted_vote", "members": [{"weight": True, "rules": REFUND}] * 2}, "above 0"),
        ({"combine": "weighted_vote", "members": [{"weight": 1, "rules": REFUND, "x": 1}] * 2}, "weight, rules"),
    ])
    def test_a_malformed_vote_is_refused(self, recipe, says):
        with pytest.raises(RuleError, match=says):
            check_recipe(recipe, self.ENRICHMENT)

    def test_the_approver_reads_every_member_and_its_weight(self):
        recipe = check_recipe(self._vote((2.0, self.REFUND), (1.25, self.BILLING)), self.ENRICHMENT)
        assert describe_recipe(recipe) == [
            {"weight": 2.0, "rules": ["If subject mentions 'refund': refund"]},
            {"weight": 1.25, "rules": ["If subject mentions 'invoice' or 'refund': billing"]}]
