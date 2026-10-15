"""Voting where three or more sources hold a field, copies discounted
(R60, the voting half; Dong, Berti-Equille and Srivastava, PVLDB 2009).
Evidence only.
"""

import random

import pytest

from core.mirror.source_record import SourceRecordStore, agreement_shown
from core.mirror.source_vote import copy_probability, disputed, vote


def held(**sources):
    return {"e1": {"city": sources}}


class TestThePlainVote:
    def test_the_value_most_sources_hold_wins(self):
        [result] = vote(held(a="Leeds", b="Leeds", c="Hull")).votes

        assert result.majority == ("a", "b")
        assert result.sources == ("a", "b", "c")

    def test_a_tie_says_nothing(self):
        [result] = vote(held(a="Leeds", b="Hull", c="York")).votes

        assert result.majority == ()

    def test_two_sources_are_not_a_vote(self):
        assert vote(held(a="Leeds", b="Hull")).votes == []

    def test_a_blank_is_not_a_vote_for_anything(self):
        assert vote(held(a="Leeds", b="Hull", c=None)).votes == []

    def test_values_compare_as_text(self):
        [result] = vote(held(a=12, b="12", c=13)).votes

        assert result.majority == ("a", "b")

    def test_only_disagreements_are_kept_per_entity(self):
        votes = vote({"e1": {"city": {"a": "L", "b": "L", "c": "L"}},
                      "e2": {"city": {"a": "L", "b": "L", "c": "H"}}}).votes

        assert [v.entity_id for v in disputed(votes)] == ["e2"]


def population(seed=1, items=200):
    """billing wrong about 20% of the time; the CRM a nightly copy of
    billing, mistakes and all; erp and web independent and mostly right."""
    rng = random.Random(seed)
    current, truth = {}, {}
    for i in range(items):
        right = f"city{rng.randrange(50)}"
        billing = right if rng.random() > 0.2 else f"wrong{rng.randrange(1000)}"
        current[f"e{i}"] = {"city": {
            "billing": billing, "crm": billing,
            "erp": right if rng.random() > 0.1 else f"wrong{rng.randrange(1000)}",
            "web": right if rng.random() > 0.1 else f"wrong{rng.randrange(1000)}"}}
        truth[f"e{i}"] = right
    return current, truth


class TestCopies:
    def test_a_copy_is_found_by_the_mistakes_it_shares(self):
        current, _ = population()

        found = vote(current).copying

        assert [c.sources for c in found] == [("billing", "crm")]
        assert found[0].shared_false > 0 and found[0].probability > 0.99

    def test_discounting_the_copy_gets_more_answers_right(self):
        """MEASURED: a plain vote is right on 156 of 200 here, because the
        copy's two votes for billing's mistakes tie the two right ones;
        with the copy counted once it is right on 189."""
        current, truth = population()

        right = sum(1 for v in vote(current).votes if v.majority
                    and current[v.entity_id]["city"][v.majority[0]] == truth[v.entity_id])

        assert right >= 185

    def test_independent_sources_that_are_usually_right_are_not_copies(self):
        """Agreeing on TRUE values is what accurate sources do; only
        shared mistakes are evidence of copying."""
        assert copy_probability(shared_true=10, shared_false=0, different=2) < 0.1
        assert copy_probability(shared_true=10, shared_false=3, different=2) > 0.99

    def test_accurate_independent_sources_are_not_copies(self):
        """FOUND BY THIS FILE'S ROUTE TEST: with every source declared
        wrong 20% of the time, two accurate sources agreeing on all
        eleven items they shared read as 65% likely to be copying. Error
        rates are estimated now; 500 items from four sources each wrong
        1% of the time, independently, find no copy."""
        rng = random.Random(5)
        current = {}
        for i in range(500):
            right = f"v{rng.randrange(100)}"
            current[f"e{i}"] = {"f": {s: right if rng.random() > 0.01 else f"w{rng.randrange(999)}"
                                      for s in "abcd"}}

        assert vote(current).copying == []

    def test_a_source_wrong_on_its_only_item_does_not_break_the_vote(self):
        """Its estimated error rate was 1.0, and log(0) raised."""
        assert vote(held(a="Leeds", b="Leeds", c="Hull")).votes[0].majority == ("a", "b")

    def test_a_long_history_does_not_underflow(self):
        assert 0 <= copy_probability(5000, 0, 800) <= 1
        assert copy_probability(5000, 400, 800) > 0.99


class TestAgreementRates:
    def test_each_source_is_counted_against_the_majority(self):
        current, _ = population()

        agreement = vote(current).agreement

        assert agreement[("city", "erp")][1] == 200
        assert agreement[("city", "erp")][0] > agreement[("city", "billing")][0]

    def test_the_browser_sees_a_rounded_rate_from_ten(self):
        assert agreement_shown(17, 20) == 80
        assert agreement_shown(9, 9) is None


class TestTheStore:
    def test_a_sync_replaces_the_last_vote(self, tmp_path):
        store = SourceRecordStore(tmp_path / "r.db")
        store.replace_vote("Customer", vote(held(a="L", b="L", c="H")))
        store.replace_vote("Customer", vote({"e2": {"city": {"a": "L", "b": "H", "c": "H"}}}))

        assert store.votes_for("Customer", "e1") == {}
        assert store.votes_for("Customer", "e2") == {
            "city": {"majority": ["b", "c"], "sources": ["a", "b", "c"]}}

    def test_copies_and_rates_are_kept_per_type(self, tmp_path):
        store = SourceRecordStore(tmp_path / "r.db")
        current, _ = population()
        store.replace_vote("Customer", vote(current))

        assert [(c["source_a"], c["source_b"]) for c in store.copying("Customer")] == [
            ("billing", "crm")]
        assert store.vote_agreement("Customer")[("city", "erp")][1] == 200
        assert store.copying("Supplier") == []


class TestTheServerSideReport:
    def test_it_names_the_copies_and_gives_counts(self, tmp_path):
        from scripts.source_track_record import report

        store = SourceRecordStore(tmp_path / "r.db")
        store.replace_vote("Customer", vote(population()[0]))

        text = report(store, ["Customer"])

        assert "billing and crm look like copies" in text
        assert "city: erp sided with the majority on" in text and "of 200" in text


@pytest.mark.parametrize("seed", [2, 3, 4])
def test_the_copy_is_found_whatever_the_draw(seed):
    current, _ = population(seed)

    assert [c.sources for c in vote(current).copying] == [("billing", "crm")]
