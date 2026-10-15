"""
Proposing that two entities might be one (GOLD-6, the inferred half).

IT NEVER DECIDES ANYTHING. Inference "only ever ADDS PROPOSALS to a
mechanism that already works without it", and a proposed merge needs
approval "ALWAYS. Never configurable, because a setting is a thing
someone turns off" (the fusion-and-identity design). This produces candidates
with a score and an explanation; the write queue decides what becomes
of them.

WEIGHTS ARE DECLARED, NOT ESTIMATED -- a decision, not a limitation. A
governed system should tell a reviewer why two records scored as they
did in terms somebody CHOSE. It also routes around a bug reproduced
across six version combinations in Splink's unsupervised training.

THE BACKEND IS OPTIONAL, so every test that needs it skips when the
extra is absent, and the tests that do NOT need it -- the settings,
the thresholds, the refusal messages -- run everywhere.
"""

import pytest

from core.mirror.matching import (
    DEFAULT_AUTO_PROPOSE_ABOVE,
    DEFAULT_REVIEW_ABOVE,
    Candidate,
    CandidateMatcher,
    SplinkMatcher,
    _agreed,
    settings_for,
)

try:  # the extra is optional by design
    import splink  # noqa: F401
    HAS_SPLINK = True
except ImportError:  # pragma: no cover - depends on the environment
    HAS_SPLINK = False

needs_splink = pytest.mark.skipif(not HAS_SPLINK, reason="the 'identity' extra is not installed")

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "b", "table": "customers", "id_column": "cust_pk"},
    "additional_storage": {"crm": {"silo": "c", "table": "contacts",
                                    "id_column": "contact_id"}},
    "identity": {
        "match_on": ["email"],
        "probabilistic": {"compare": ["name", "postcode"], "block_on": ["postcode"]},
    },
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data"},
        "email": {"type": "data"},
        "name": {"type": "data"},
        "postcode": {"type": "data"},
    },
}
ROWS = {
    None: [{"cust_pk": "c1", "name": "Ada Okafor", "postcode": "LS1 4AB"},
           {"cust_pk": "c2", "name": "Ben Carter", "postcode": "HU1 2CD"}],
    "crm": [{"contact_id": "9f2a", "name": "Ada Okafor", "postcode": "LS1 4AB"},
            {"contact_id": "7c1b", "name": "Zoe N", "postcode": "HU1 2CD"}],
}


class TestWhatADeploymentDeclares:
    def test_a_type_declaring_no_inference_gets_none(self):
        without = {**TYPE, "identity": {"match_on": ["email"]}}

        assert settings_for(without) is None

    def test_the_declared_fields_and_thresholds_are_read(self):
        settings = settings_for(TYPE)

        assert settings.compare == ("name", "postcode")
        assert settings.auto_propose_above == DEFAULT_AUTO_PROPOSE_ABOVE
        assert settings.review_above == DEFAULT_REVIEW_ABOVE

    @pytest.mark.parametrize("declared, message", [
        ({"compare": []}, "non-empty"),
        ({"compare": ["nickname"]}, "unknown field"),
        ({"compare": ["name"], "fuzzy": True}, "unknown identity.probabilistic key"),
        ({"compare": ["name"], "review_above": 0.99, "auto_propose_above": 0.5}, "thresholds"),
        ("yes", "must be a mapping"),
    ])
    def test_a_malformed_declaration_is_refused(self, declared, message):
        """A deployment that meant to enable matching and typed a key
        wrongly should be told, not quietly left deterministic."""
        type_def = {**TYPE, "identity": {"match_on": ["email"], "probabilistic": declared}}

        with pytest.raises(ValueError, match=message):
            settings_for(type_def)


class TestTheThresholds:
    def test_the_default_ladder_is_the_documented_one(self):
        """1 field agreeing is nothing, 2 reaches review, 3 proposes --
        worked out from the weights rather than chosen by feel, after a
        first attempt left the feature inert."""
        prior, m, u = 0.001, 0.9, 0.01

        def probability(fields):
            odds = (m / u) ** fields * (prior / (1 - prior))
            return odds / (1 + odds)

        assert probability(1) < DEFAULT_REVIEW_ABOVE
        assert DEFAULT_REVIEW_ABOVE < probability(2) < DEFAULT_AUTO_PROPOSE_ABOVE
        assert probability(3) > DEFAULT_AUTO_PROPOSE_ABOVE


class TestTheInterface:
    def test_the_backend_satisfies_the_interface_we_declared(self):
        """Otherwise the protocol is a comment, and nothing would
        notice a backend drifting away from it."""
        assert isinstance(SplinkMatcher(), CandidateMatcher)


class TestWithoutTheExtra:
    def test_a_type_declaring_nothing_needs_no_backend(self):
        """The deterministic rule keeps working with nothing
        installed -- which is what makes the optional extra safe."""
        without = {**TYPE, "identity": {"match_on": ["email"]}}

        assert SplinkMatcher().candidates(without, ROWS) == []


@needs_splink
class TestScoring:
    def test_it_finds_the_same_person_across_two_sources(self):
        candidates = SplinkMatcher().candidates(TYPE, ROWS)

        pairs = {frozenset((candidate.left_id, candidate.right_id))
                 for candidate in candidates}
        assert frozenset(("primary:c1", "crm:9f2a")) in pairs

    def test_it_does_not_propose_two_different_people(self):
        """Ben and Zoe share a postcode and nothing else."""
        candidates = SplinkMatcher().candidates(TYPE, ROWS)

        pairs = {frozenset((candidate.left_id, candidate.right_id))
                 for candidate in candidates}
        assert frozenset(("primary:c2", "crm:7c1b")) not in pairs

    def test_the_explanation_says_which_fields_agreed(self):
        """A reviewer reads this, not a score."""
        candidate = SplinkMatcher().candidates(TYPE, ROWS)[0]

        assert candidate.agreement == {"name": True, "postcode": True}

    def test_two_agreeing_fields_land_in_REVIEW_not_proposal(self):
        candidate = SplinkMatcher().candidates(TYPE, ROWS)[0]

        assert DEFAULT_REVIEW_ABOVE < candidate.score < DEFAULT_AUTO_PROPOSE_ABOVE

    def test_the_id_carries_its_source(self):
        """The whole point is that two sources call one object
        different things."""
        candidate = SplinkMatcher().candidates(TYPE, ROWS)[0]

        assert candidate.left_id.split(":")[0] in {"primary", "crm"}

    def test_blocking_changes_what_is_compared_not_the_verdict(self):
        """Two people with the same name in different towns are not
        proposed -- with or without the declared blocking.

        RECORDED HONESTLY AFTER A CONTROL PROVED NOTHING TWICE.
        Removing the declared blocking does not change this result,
        because the pair is scored and then rejected by the threshold
        anyway. Blocking decides WHICH PAIRS ARE GENERATED, which is a
        question of scale -- a matcher blocking on nothing compares
        every row against every other -- not of the answer. Pretending
        otherwise would be a test that passes for the wrong reason.
        """
        rows = {
            None: [{"cust_pk": "c1", "name": "Ada Okafor", "postcode": "LS1 4AB"}],
            "crm": [{"contact_id": "9f2a", "name": "Ada Okafor", "postcode": "HU1 2CD"}],
        }

        assert SplinkMatcher().candidates(TYPE, rows) == []

    def test_the_declared_blocking_reaches_the_backend(self):
        """What CAN be asserted without the backend: the declaration is
        read and passed on."""
        assert settings_for(TYPE).block_on == ("postcode",)

    def test_no_rows_means_no_candidates(self):
        assert SplinkMatcher().candidates(TYPE, {None: [], "crm": []}) == []

    def test_the_harness_can_ask_for_every_pair_compared(self):
        """R59: a true match scored low and one never compared are
        different faults, so evaluation asks for the low scores too.
        Ben and Zoe share only a postcode, so the default leaves them
        out and `at_least=0.0` does not."""
        ben_and_zoe = frozenset(("primary:c2", "crm:7c1b"))

        everything = SplinkMatcher().candidates(TYPE, ROWS, at_least=0.0)

        assert ben_and_zoe in {frozenset((c.left_id, c.right_id)) for c in everything}
        assert all(c.score < DEFAULT_REVIEW_ABOVE for c in everything
                   if frozenset((c.left_id, c.right_id)) == ben_and_zoe)


class TestANullIsNotADISAGREEMENT:
    """Splink's gamma is THREE-VALUED and was being read as two.

    NEGATIVE means the comparison could not be made because a value
    was null. ZERO means it was made and nothing matched. POSITIVE
    names which match level fired. `bool(gamma > 0)` folded the first
    two together, so "one of these records has no email" was recorded
    as "these two emails differ" -- and that went to a human being
    asked whether the records are the same person.

    IT BIASES IN ONE DIRECTION, which is why it is worth a class. A
    null is not evidence against a match; presented as a
    disagreement, it argues against one. `masked_review` already had
    the word for this -- UNCOMPARED, "not compared" -- and no way to
    reach it.
    """

    def test_a_null_comparison_is_not_compared(self):
        assert _agreed(-1) is None

    def test_a_real_disagreement_is_still_a_disagreement(self):
        """THE CONTROL. Returning None for everything would satisfy
        the test above and lose every verdict the matcher found."""
        assert _agreed(0) is False

    @pytest.mark.parametrize("gamma", [1, 2, 3])
    def test_any_match_level_is_agreement(self, gamma):
        """Splink's levels are ordered -- exact, then progressively
        looser -- and all of them are a match. A rule reading only
        gamma == 1 would call a fuzzy match a disagreement."""
        assert _agreed(gamma) is True

    def test_a_field_the_backend_said_nothing_about_is_not_compared(self):
        """Missing entirely is not False either. Inventing a
        disagreement from an absent key is the same error with a
        different cause."""
        assert _agreed(None) is None

    @pytest.mark.parametrize("gamma", ["2", "-1", "0"])
    def test_it_reads_what_a_dataframe_actually_yields(self, gamma):
        """pandas hands back numpy scalars and, through some paths,
        strings. A comparison written against `int` would silently
        take the wrong branch rather than raise."""
        assert _agreed(gamma) is {"2": True, "-1": None, "0": False}[gamma]

    def test_a_value_it_cannot_read_is_not_compared_rather_than_differ(self):
        """REFUSES DOWNWARD. An unparseable gamma means the backend
        said something this code does not understand, and the safe
        reading of that is "no verdict", not "they disagree"."""
        assert _agreed("unexpected") is None

    def test_the_candidate_carries_the_three_values_through(self):
        """The dataclass widened with it; a dict[str, bool] would
        coerce the third state away at the first type check."""
        candidate = Candidate(left_id="a", right_id="b", score=0.9,
                               agreement={"name": True, "email": None, "postcode": False})

        assert candidate.agreement["email"] is None


class TestTheGateRunsThem:
    """COORD-3. Every test above that needs the backend SKIPS without it,
    and CI installs only requirements-dev.lock -- which had no splink. So
    GOLD-6's inference was untested in every environment that gates a
    merge, and the suite was green about it."""

    def test_the_lock_ci_installs_carries_the_backend(self):
        from pathlib import Path

        lock = (Path(__file__).resolve().parents[2] / "requirements-dev.lock").read_text()
        assert any(line.startswith("splink==") for line in lock.splitlines())

    def test_in_ci_the_backend_is_there(self):
        """GitHub Actions sets CI=true. There, a missing backend is a
        failure rather than eight quiet skips."""
        import os

        if os.environ.get("CI") != "true":
            pytest.skip("only CI must have the backend; it is optional elsewhere")
        assert HAS_SPLINK, "requirements-dev.lock should have installed splink"
