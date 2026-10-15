"""The matching cascade, and the close level it gained (R56).

Each stage sees only what earlier stages left undecided: the declared
rule first, then scoring. And a field declared fuzzy has a third
answer, CLOSE, which is neither agreement nor difference.
"""

import json

import pytest

from core.masked_review import CLOSE, masked_comparison
from core.mirror.match_calibration import scoring_key
from core.mirror.match_cascade import PROBABILISTIC, RULE, cascade, rule_groups
from core.mirror.matching import Candidate, SplinkMatcher, settings_for

try:  # the extra is optional by design
    import splink  # noqa: F401
    HAS_SPLINK = True
except ImportError:  # pragma: no cover - depends on the environment
    HAS_SPLINK = False

needs_splink = pytest.mark.skipif(not HAS_SPLINK, reason="the 'identity' extra is not installed")

TYPE = {
    "storage": {"silo": "b", "table": "customers", "id_column": "pk"},
    "additional_storage": {"crm": {"silo": "c", "table": "contacts", "id_column": "cid"}},
    "identity": {"match_on": ["email"],
                 "probabilistic": {"compare": ["name", "email"], "block_on": ["region"]}},
    "fields": {"email": {"type": "data"}, "name": {"type": "data"}, "region": {"type": "data"}},
}


def fuzzy(type_def=TYPE, declared=("name", "email")):
    probabilistic = {**type_def["identity"]["probabilistic"], "fuzzy": list(declared)}
    return {**type_def, "identity": {**type_def["identity"], "probabilistic": probabilistic}}


def scored(*candidates):
    def score(type_def, rows, at_least=None):
        return list(candidates)
    return score


ROWS = {None: [{"pk": "c1", "email": "ada@x.org", "name": "Ada Okafor", "region": "n"},
               {"pk": "c2", "email": "ben@x.org", "name": "Ben Carter", "region": "n"},
               {"pk": "c3", "email": None, "name": "Cy Dee", "region": "n"}],
        "crm": [{"cid": "9f", "email": "ada@x.org", "name": "Ada Okafor", "region": "n"},
                {"cid": "7c", "email": None, "name": "Cy Dee", "region": "n"}]}


class TestTheRuleIsStageOne:
    def test_records_sharing_the_declared_key_are_grouped(self):
        groups = rule_groups(TYPE, ROWS)

        assert groups["primary:c1"] == groups["crm:9f"]
        # A unique key, or a missing one, decided nothing.
        assert set(groups) == {"primary:c1", "crm:9f"}

    def test_scoring_never_proposes_what_the_rule_merged(self):
        found = cascade(TYPE, ROWS, scored(Candidate("primary:c1", "crm:9f", 0.89),
                                           Candidate("primary:c3", "crm:7c", 0.89)))

        assert [(s.left_id, s.right_id, s.stage) for s in found] == [
            ("primary:c3", "crm:7c", PROBABILISTIC)]

    def test_the_harness_gets_the_rules_pairs_at_one(self):
        found = cascade(TYPE, ROWS, scored(), include_rule=True)

        assert [(s.left_id, s.right_id, s.score, s.stage, dict(s.agreement)) for s in found] == [
            ("crm:9f", "primary:c1", 1.0, RULE, {"email": True})]

    def test_the_threshold_reaches_the_scoring_stage(self):
        asked = []

        def score(type_def, rows, at_least=None):
            asked.append(at_least)
            return []

        cascade(TYPE, ROWS, score, at_least=0.0)

        assert asked == [0.0]


class TestTheCloseLevel:
    def test_one_edit_is_the_default_and_a_mapping_sets_it(self):
        assert settings_for(fuzzy()).fuzzy == (("name", 1), ("email", 1))
        declared = {**TYPE["identity"]["probabilistic"], "fuzzy": {"name": 2}}
        assert settings_for({**TYPE, "identity": {"match_on": ["email"],
                                                  "probabilistic": declared}}).fuzzy == (
            ("name", 2),)

    def test_a_reviewer_is_told_close_not_agree(self):
        entries = masked_comparison({"email": CLOSE}, {"email": "ada@x.org"},
                                    {"email": "ada@x.orh"}, {"email"})

        assert entries[0]["verdict"] == "close"

    def test_provenance_names_the_close_level_only_when_declared(self):
        plain = SplinkMatcher().provenance(TYPE)
        declared = SplinkMatcher().provenance(fuzzy())

        assert "fuzzy" not in plain and "m_close" not in plain
        assert declared["fuzzy"] == {"name": 1, "email": 1}
        assert (declared["m_close"], declared["u_close"]) == (0.08, 0.001)

    def test_calibration_evidence_survives_the_upgrade_but_not_a_new_level(self):
        """A type that declares no fuzzy fields keeps its R57 evidence --
        its provenance is what it was. One that does is scored
        differently, so its old rejections are not comparable."""
        plain = SplinkMatcher().provenance(TYPE)

        # EXACTLY THE KEYS R62 RECORDED BEFORE R56, so a stored rejection's
        # provenance still keys the same as today's.
        assert set(plain) == {"matcher", "version", "m_probability", "u_probability", "prior",
                              "compare", "block_on", "auto_propose_above", "review_above"}
        assert scoring_key(json.loads(json.dumps(plain))) == scoring_key(plain)
        assert scoring_key(plain) != scoring_key(SplinkMatcher().provenance(fuzzy()))


@needs_splink
class TestTheScores:
    """The table SplinkMatcher.__init__ states, measured."""

    BASE = {"pk": "a", "name": "Ada Okafor", "email": "ada@okafor.org", "region": "n"}

    def score(self, change, type_def=None):
        rows = {None: [self.BASE, {**self.BASE, "pk": "b", **change}]}
        found = SplinkMatcher().candidates(type_def or fuzzy(), rows, at_least=0.0)
        return round(found[0].score, 3), found[0].agreement

    def test_both_exact_scores_as_it_always_did(self):
        assert self.score({}) == (0.890, {"name": True, "email": True})
        assert self.score({}, TYPE)[0] == 0.890

    def test_a_typo_now_reaches_review(self):
        score, agreement = self.score({"email": "ada@okafro.org"})

        assert score == 0.878 and agreement == {"name": True, "email": "close"}
        # The same pair, exact only, scored nothing.
        assert self.score({"email": "ada@okafro.org"}, TYPE)[0] < 0.01

    def test_two_edits_are_not_close_by_default(self):
        score, agreement = self.score({"name": "A. Okafor"})

        assert agreement["name"] is False and score < 0.01

    def test_a_blank_is_still_not_evidence(self):
        assert self.score({"email": None}) == (0.083, {"name": True, "email": None})


class TestTheReportSaysClose:
    def test_an_error_line_says_close_not_agrees(self):
        from core.mirror.match_evaluation import evaluate, labels_from_clusters
        from scripts.evaluate_matching import report

        labels = labels_from_clusters({"a": 1, "b": 1}, "test")
        found = [Candidate("a", "b", 0.07, {"email": CLOSE, "name": None})]

        text = report(evaluate(found, labels, errors_at=0.8))

        assert "email close, name uncompared" in text
