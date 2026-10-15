"""Measuring the matcher against labels (R59).

The harness decides nothing; these tests hold it to counting correctly,
to refusing a recall it cannot measure, and to synthetic labels that
say what they claim.
"""

from types import SimpleNamespace

import pytest

from core.mirror.match_evaluation import (
    evaluate,
    labels_from_clusters,
    labels_from_pairs,
    pair,
    synthetic_duplicates,
    wilson,
)
from scripts.evaluate_matching import _labels_file, report


def candidate(left, right, score, **agreement):
    return SimpleNamespace(left_id=left, right_id=right, score=score, agreement=agreement)


# a~b and c~d are the same; e is alone.
CLUSTERS = {"a": 1, "b": 1, "c": 2, "d": 2, "e": 3}


class TestCounting:
    def test_each_threshold_counts_what_scores_at_least_it(self):
        labels = labels_from_clusters(CLUSTERS, "test")
        scored = [candidate("a", "b", 0.99), candidate("a", "e", 0.9),
                  candidate("c", "d", 0.5)]

        rows = {r.threshold: r for r in evaluate(scored, labels).rows}

        assert (rows[0.99].true_positives, rows[0.99].false_positives,
                rows[0.99].false_negatives) == (1, 0, 1)
        assert (rows[0.9].true_positives, rows[0.9].false_positives) == (1, 1)
        assert (rows[0.5].true_positives, rows[0.5].false_negatives) == (2, 0)
        assert rows[0.5].precision == pytest.approx(2 / 3)
        assert rows[0.5].recall == 1.0

    def test_a_pair_named_both_ways_is_one_pair(self):
        labels = labels_from_clusters(CLUSTERS, "test")

        result = evaluate([candidate("a", "b", 0.9), candidate("b", "a", 0.9)], labels)

        assert result.rows[0].true_positives == 1

    def test_the_declared_thresholds_are_rows_and_named(self):
        labels = labels_from_clusters(CLUSTERS, "test")

        result = evaluate([candidate("a", "b", 0.89)], labels,
                          declared={"review_above": 0.8, "auto_propose_above": 0.95})

        named = {r.declared_as: r for r in result.rows if r.declared_as}
        # Nothing scores 0.95, which is exactly what a reader needs to see.
        assert named["auto_propose_above"].true_positives == 0
        assert named["review_above"].true_positives == 1

    def test_a_match_blocking_never_compared_is_a_miss_with_no_score(self):
        labels = labels_from_clusters(CLUSTERS, "test")

        result = evaluate([candidate("a", "b", 0.99)], labels, errors_at=0.8)

        assert result.compared_matches == 1
        assert result.pairs_completeness == 0.5
        assert [(e.left_id, e.right_id, e.kind, e.score) for e in result.errors] == [
            ("c", "d", "missed", None)]

    def test_errors_name_both_kinds_at_the_threshold_asked(self):
        labels = labels_from_clusters(CLUSTERS, "test")

        result = evaluate([candidate("a", "e", 0.9, name=True),
                           candidate("a", "b", 0.3, name=False),
                           candidate("c", "d", 0.95)], labels, errors_at=0.8)

        assert {(e.left_id, e.right_id, e.kind) for e in result.errors} == {
            ("a", "e", "false match"), ("a", "b", "missed")}


class TestLabelsThatCoverOnlySomePairs:
    def test_recall_is_not_measurable_and_says_so(self):
        labels = labels_from_pairs([("a", "b", True), ("a", "e", False)], "decisions")

        result = evaluate([candidate("a", "b", 0.9), candidate("a", "e", 0.9),
                           candidate("c", "d", 0.9)], labels)

        row = result.rows[0]
        assert (row.true_positives, row.false_positives, row.unlabelled) == (1, 1, 1)
        assert row.false_negatives is None
        assert row.recall is None and row.recall_interval is None
        assert result.compared_matches is None
        assert "RECALL IS NOT MEASURABLE" in report(result)

    def test_an_unlabelled_miss_is_not_listed_as_an_error(self):
        labels = labels_from_pairs([("a", "b", True)], "decisions")

        result = evaluate([candidate("a", "b", 0.9)], labels, errors_at=0.95)

        # a~b IS labelled and fell below 0.95, so it is listed; nothing
        # is invented for pairs no label covers.
        assert [(e.left_id, e.kind) for e in result.errors] == [("a", "missed")]


class TestIntervals:
    def test_wilson_matches_the_published_formula(self):
        # 3 of 3: the textbook interval would be (1, 1); Wilson's is wide.
        low, high = wilson(3, 3)
        assert low == pytest.approx(0.4385, abs=1e-4)
        assert high == 1.0
        low, high = wilson(0, 3)
        assert low == 0.0
        assert high == pytest.approx(0.5615, abs=1e-4)

    def test_no_trials_is_no_interval(self):
        assert wilson(0, 0) is None


TYPE = {
    "storage": {"silo": "s", "table": "customers", "id_column": "pk"},
    "fields": {"name": {"type": "data", "column": "full_name"},
               "postcode": {"type": "data"}},
}
ROWS = {None: [{"pk": f"c{i}", "full_name": f"Person Number{i}", "postcode": f"LS{i} 1AB"}
               for i in range(20)],
        "crm": [{"contact_id": "x", "full_name": "Person Number3"}]}


class TestSyntheticCopies:
    def test_the_same_seed_gives_the_same_copies(self):
        one, _ = synthetic_duplicates(TYPE, ROWS, ["name", "postcode"], 5, rate=0.5, seed=7)
        two, _ = synthetic_duplicates(TYPE, ROWS, ["name", "postcode"], 5, rate=0.5, seed=7)
        other, _ = synthetic_duplicates(TYPE, ROWS, ["name", "postcode"], 5, rate=0.5, seed=8)

        assert one == two
        assert one != other

    def test_copies_are_added_and_the_originals_left_alone(self):
        before = [dict(r) for r in ROWS[None]]

        rows, labels = synthetic_duplicates(TYPE, ROWS, ["name"], 4, seed=1)

        assert ROWS[None] == before
        assert len(rows[None]) == 24
        assert rows["crm"] == ROWS["crm"]
        assert len(labels.matches) == 4
        assert labels.exhaustive

    def test_a_copy_matches_its_original_and_nothing_else(self):
        rows, labels = synthetic_duplicates(TYPE, ROWS, ["name"], 2, rate=0.0, seed=3)
        copy = rows[None][-1]
        original = next(r for r in ROWS[None] if r["full_name"] == copy["full_name"])
        stranger = next(r for r in ROWS[None] if r is not original)

        copy_id, original_id = f"primary:{copy['pk']}", f"primary:{original['pk']}"
        assert labels.verdict(pair(copy_id, original_id)) is True
        assert labels.verdict(pair(copy_id, f"primary:{stranger['pk']}")) is False
        # Two ORIGINAL rows may be real duplicates already: unlabelled.
        assert labels.verdict(pair(original_id, f"primary:{stranger['pk']}")) is None
        assert "exact copy" in labels.notes[copy_id]

    def test_damage_goes_through_the_bound_column_and_is_recorded(self):
        rows, labels = synthetic_duplicates(TYPE, ROWS, ["name"], 10, rate=1.0, seed=2)
        by_id = {f"primary:{r['pk']}": r for r in ROWS[None]}
        origin = {copy: original for copy, original in
                  (sorted(p, key=lambda i: "synthetic" not in i) for p in labels.matches)}

        for copy in rows[None][20:]:
            original = by_id[origin[f"primary:{copy['pk']}"]]
            # The NAME column was damaged (rate 1.0); postcode, not
            # compared, was left alone.
            assert copy["full_name"] != original["full_name"]
            assert copy["postcode"] == original["postcode"]
        assert all("name " in note for note in labels.notes.values())


class TestTheLabelsFile:
    def test_both_formats_are_read(self, tmp_path):
        ours = tmp_path / "ours.csv"
        ours.write_text("left,right,is_match\nprimary:a,primary:b,true\nprimary:a,crm:x,0\n")
        splinks = tmp_path / "splink.csv"
        splinks.write_text("unique_id_l,unique_id_r,clerical_match_score\n"
                           "primary:a,primary:b,0.9\nprimary:a,crm:x,0.2\n")

        for path in (ours, splinks):
            labels = _labels_file(path)
            assert labels.matches == {("primary:a", "primary:b")}
            assert labels.verdict(("crm:x", "primary:a")) is False
            assert not labels.exhaustive

    def test_a_file_without_the_columns_is_refused_by_name(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("a,b\n1,2\n")

        with pytest.raises(ValueError, match="left,right,is_match"):
            _labels_file(bad)
