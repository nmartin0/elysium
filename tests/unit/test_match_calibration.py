"""Pre-selecting waiting merges with a stated error rate (R57).

The guarantee is statistical, so beside the arithmetic there is a
simulation: many runs drawn from known distributions, and the realised
share of wrong merges among those pre-selected must stay at or under
the declared rate on average. That is the claim the screen makes.
"""

import json
import random
from types import SimpleNamespace

import pytest

from api.routes import _preselection
from core.identity_decisions import APPROVED, REJECTED, MergeDecisionStore
from core.mirror.match_calibration import (
    CALIBRATED,
    UNCALIBRATED,
    benjamini_hochberg,
    calibrate,
    conformal_p,
    rejections_needed,
)
from core.mirror.matching import SplinkMatcher

TYPE = {"storage": {"silo": "s", "table": "t", "id_column": "pk"},
        "fields": {"name": {"type": "data"}, "postcode": {"type": "data"}},
        "identity": {"probabilistic": {"compare": ["name", "postcode"],
                                       "review_above": 0.8, "auto_propose_above": 0.95}}}
NOW = SplinkMatcher().provenance(TYPE)


def proposal(pid, score, decision, provenance=NOW):
    return SimpleNamespace(proposal_id=pid, score=score, decision=decision,
                           provenance=json.dumps(provenance) if provenance else "")


def rejections(n, score=0.85, **kwargs):
    return [proposal(f"r{i}", score, REJECTED, **kwargs) for i in range(n)]


class TestTheArithmetic:
    @pytest.mark.parametrize("alpha, needed", [(0.05, 19), (0.1, 9), (0.2, 4), (0.01, 99)])
    def test_the_fewest_rejections_that_can_select_anything(self, alpha, needed):
        assert rejections_needed(alpha) == needed
        # ...because the smallest p-value n0 rejections allow is 1/(n0+1).
        assert 1 / (needed + 1) <= alpha < 1 / needed

    def test_a_conformal_p_value_counts_rejections_scoring_as_high(self):
        reference = [0.81, 0.85, 0.85, 0.9]

        assert conformal_p(0.95, reference) == 1 / 5
        assert conformal_p(0.85, reference) == 4 / 5  # ties count against it
        assert conformal_p(0.80, reference) == 1.0

    def test_benjamini_hochberg_steps_up(self):
        # 0.04 is above 2*0.05/4 at rank 2 but 0.045 is under 4*0.05/4:
        # the largest qualifying rank decides, so all four are selected.
        p = {"a": 0.01, "b": 0.04, "c": 0.042, "d": 0.045}
        assert benjamini_hochberg(p, 0.05) == {"a", "b", "c", "d"}
        assert benjamini_hochberg({"a": 0.01, "b": 0.04, "c": 0.3}, 0.05) == {"a"}
        assert benjamini_hochberg({}, 0.05) == frozenset()


class TestWhatCountsAsEvidence:
    def test_too_few_rejections_is_uncalibrated_and_selects_nothing(self):
        found = calibrate(rejections(18) + [proposal("p", 0.94, "pending")], NOW)

        assert found.status == UNCALIBRATED
        assert (found.rejections_used, found.rejections_needed) == (18, 19)
        assert found.selected == frozenset()

    def test_enough_rejections_select_what_scores_above_them(self):
        found = calibrate(rejections(19) + [proposal("high", 0.9, "pending")], NOW)

        assert found.status == CALIBRATED
        assert found.selected == {"high"}

    def test_more_waiting_pairs_need_more_rejections(self):
        """BH's bar for the best of m pairs is alpha/m. With two waiting,
        19 rejections give p = 1/20, above 0.025; 39 give exactly 0.025."""
        waiting = [proposal("high", 0.9, "pending"), proposal("low", 0.85, "pending")]

        assert calibrate(rejections(19) + waiting, NOW).selected == frozenset()
        assert calibrate(rejections(39) + waiting, NOW).selected == {"high"}

    def test_approvals_are_not_rejections(self):
        approvals = [proposal(f"a{i}", 0.85, APPROVED) for i in range(30)]

        assert calibrate(approvals, NOW).status == UNCALIBRATED

    def test_a_rejection_that_was_pre_selected_does_not_count(self):
        """Shown ticked, its decision leaned on the tick."""
        ticked = rejections(19, score=0.96)

        assert calibrate(ticked, NOW).rejections_used == 0

    def test_a_rejection_scored_under_other_weights_does_not_count(self):
        other = {**NOW, "u_probability": 0.05}

        assert calibrate(rejections(30, provenance=other), NOW).rejections_used == 0
        assert calibrate(rejections(30, provenance=None), NOW).rejections_used == 0

    def test_a_new_splink_version_does_not_discard_the_evidence(self):
        """Declared weights score the same across versions."""
        upgraded = {**NOW, "version": "99.0"}

        assert calibrate(rejections(19, provenance=upgraded), NOW).status == CALIBRATED

    def test_a_pending_pair_above_the_declared_threshold_is_not_a_candidate(self):
        found = calibrate(rejections(19) + [proposal("top", 0.97, "pending")], NOW)

        assert found.considered == 0 and found.selected == frozenset()


class TestTheGuarantee:
    def test_the_false_merge_rate_holds_on_average(self):
        """Nulls and matches drawn from overlapping score distributions;
        over 400 runs the mean share of non-matches among those selected
        must not exceed alpha (with room for simulation noise), and the
        method must actually select something -- a test passed by never
        selecting would prove nothing."""
        rng = random.Random(11)
        alpha, runs = 0.1, 400
        fdps, selected_total = [], 0
        for _ in range(runs):
            reference = [rng.uniform(0.80, 0.93) for _ in range(40)]
            pending, truth = {}, {}
            for i in range(30):
                is_match = rng.random() < 0.5
                pending[f"p{i}"] = (rng.uniform(0.90, 0.95) if is_match
                                    else rng.uniform(0.80, 0.93))
                truth[f"p{i}"] = is_match
            props = ([proposal(f"r{i}", s, REJECTED) for i, s in enumerate(reference)]
                     + [proposal(pid, s, "pending") for pid, s in pending.items()])
            chosen = calibrate(props, NOW, alpha).selected
            selected_total += len(chosen)
            fdps.append(sum(1 for pid in chosen if not truth[pid]) / max(1, len(chosen)))

        assert selected_total > runs  # it selects, on average more than one a run
        assert sum(fdps) / runs <= alpha + 0.02


class TestTheListing:
    def _store(self, tmp_path, n_rejected, pending_score):
        store = MergeDecisionStore(tmp_path / "d.db")
        provenance = json.dumps(NOW, sort_keys=True)
        for i in range(n_rejected):
            pid = store.propose("Customer", f"primary:a{i}", f"primary:b{i}", 0.85,
                                provenance=provenance)
            store.decide(pid, REJECTED, "reviewer")
        store.propose("Customer", "primary:x", "primary:y", pending_score,
                      provenance=provenance)
        waiting = next(p for p in store.proposals("Customer") if p.decision == "pending")
        return store, waiting

    def test_a_calibrated_type_ticks_a_pair_below_the_declared_threshold(self, tmp_path):
        store, waiting = self._store(tmp_path, 19, 0.9)

        found = _preselection({"Customer": TYPE}, store, waiting, {})

        assert found["preselected_by"] == "calibrated"
        assert found["high_confidence"] is True
        assert found["calibration"] == {"status": "calibrated", "false_merge_rate": 0.05}

    def test_one_rejection_short_ticks_nothing_and_says_uncalibrated(self, tmp_path):
        store, waiting = self._store(tmp_path, 18, 0.9)

        found = _preselection({"Customer": TYPE}, store, waiting, {})

        assert found["preselected_by"] is None
        assert found["calibration"]["status"] == "uncalibrated"
        # No count reaches the viewer: the rejections span compartments.
        assert set(found["calibration"]) == {"status", "false_merge_rate"}

    def test_the_type_declares_its_rate(self, tmp_path):
        store, waiting = self._store(tmp_path, 9, 0.9)
        lenient = {**TYPE, "identity": {"probabilistic": {
            **TYPE["identity"]["probabilistic"], "false_merge_rate": 0.1}}}

        found = _preselection({"Customer": lenient}, store, waiting, {})

        assert found["preselected_by"] == "calibrated"
        assert found["calibration"]["false_merge_rate"] == 0.1


class TestTheServerSideReport:
    def test_it_gives_the_counts_the_screen_leaves_out(self, tmp_path):
        from core.mirror.matching import settings_for
        from scripts.evaluate_matching import calibration_report

        store = MergeDecisionStore(tmp_path / "identity_decisions.db")
        provenance = json.dumps(NOW, sort_keys=True)
        for i in range(4):
            store.decide(store.propose("Customer", f"primary:a{i}", f"primary:b{i}", 0.85,
                                       provenance=provenance), REJECTED, "reviewer")

        text = calibration_report(tmp_path, "Customer", TYPE, settings_for(TYPE))

        assert "UNCALIBRATED at false_merge_rate 0.05" in text
        assert "4 comparable rejection(s)" in text and "at least 19 needed" in text
