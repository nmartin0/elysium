"""Records whose numbers are unusual for their kind (R51): the
declaration, the scoring, and the store -- on synthetic records whose
oddities were planted."""

import random

import pytest

from core.ontology.unusual_checks import validate_unusual_checks
from core.unusual import MAX_FLAGS, MIN_GROUP, find_unusual
from core.unusual_flags import UnusualFlagStore


def _records(count=3_000, seed=0):
    """Amounts that depend on the category, plus two kinds of oddity:
    WRONG_KIND -- an amount ordinary for the table but not its category;
    EXTREME -- an amount far beyond its own category's."""
    rng = random.Random(seed)
    usual = {"subscription": (50, 5), "hardware": (300, 30), "refund": (-80, 10)}
    rows = []
    for index in range(count):
        category = rng.choice(list(usual))
        mean, spread = usual[category]
        rows.append({"id": f"r{index}", "category": category,
                     "currency": rng.choice(["USD", "EUR"]),
                     "amount": round(rng.gauss(mean, spread), 2)})
    return rows


WRONG_KIND = {"r10": 300.0, "r11": 300.0, "r12": 50.0}
EXTREME = {"r20": 9_000.0}


def _planted():
    rows = _records()
    for row in rows:
        if row["id"] in WRONG_KIND:
            row["category"] = "subscription" if WRONG_KIND[row["id"]] == 300.0 else "hardware"
            row["amount"] = WRONG_KIND[row["id"]]
        if row["id"] in EXTREME:
            row["category"], row["amount"] = "hardware", EXTREME[row["id"]]
    return rows


class TestFinding:
    def test_a_value_ordinary_for_the_table_but_wrong_for_its_kind_is_found(self):
        flags, _ = find_unusual(_planted(), "id", ["amount"], ["category"])
        found = {flag.record_id for flag in flags}
        assert set(WRONG_KIND) <= found and set(EXTREME) <= found

    def test_without_its_kind_the_wrong_kind_is_missed(self):
        """The reason `within` exists: against the whole table, 300 is an
        ordinary hardware amount and 50 an ordinary subscription."""
        flags, _ = find_unusual(_planted(), "id", ["amount"], [])
        assert not set(WRONG_KIND) & {flag.record_id for flag in flags}

    def test_clean_records_raise_nothing(self):
        flags, total = find_unusual(_records(), "id", ["amount"], ["category"])
        assert total <= 3, "a published cut-off, not a quota: a few at most by chance"

    def test_the_same_records_give_the_same_flags(self):
        assert find_unusual(_planted(), "id", ["amount"], ["category", "currency"]) == \
            find_unusual(_planted(), "id", ["amount"], ["category", "currency"])

    def test_it_says_why_in_words(self):
        flags, _ = find_unusual(_planted(), "id", ["amount"], ["category"])
        reason = next(flag for flag in flags if flag.record_id == "r10").reason()
        assert reason.startswith("amount 300 is far above the usual 49.8")
        assert "records with category subscription; nine in ten of them are between" in reason

    def test_a_kind_too_small_to_judge_is_not_judged(self):
        rows = _records(count=200)
        rows += [{"id": f"x{index}", "category": "rare", "currency": "USD",
                  # A SPREAD, so only its size can stop it being judged.
                  "amount": 1.0 + index * 0.1 if index else 10_000.0}
                 for index in range(MIN_GROUP - 1)]
        flags, _ = find_unusual(rows, "id", ["amount"], ["category"])
        assert not any(flag.record_id.startswith("x") for flag in flags)

    def test_a_kind_with_no_spread_is_not_judged(self):
        rows = [{"id": f"s{index}", "category": "flat", "amount": 5.0} for index in range(30)]
        rows.append({"id": "odd", "category": "flat", "amount": 6.0})
        assert find_unusual(rows, "id", ["amount"], ["category"]) == ([], 0)

    def test_the_furthest_first_and_at_most_a_capped_number(self):
        rows = _records()
        for row in rows[:200]:
            row["category"], row["amount"] = "hardware", 50_000.0 + float(row["id"][1:])
        flags, total = find_unusual(rows, "id", ["amount"], ["category"])
        assert len(flags) == MAX_FLAGS and total >= 200
        scores = [abs(flag.score) for flag in flags]
        assert scores == sorted(scores, reverse=True)


class TestTheDeclaration:
    def _types(self, **unusual):
        return {"Transaction": {"id_field": "id", "unusual": unusual or {
            "numbers": ["amount"], "within": ["category"]}, "fields": {
            "id": {"type": "data"}, "amount": {"type": "data", "data_type": "decimal"},
            "category": {"type": "data"}, "booked": {"type": "data", "data_type": "date"},
            "salary": {"type": "data", "data_type": "number", "classification": ["pii"]},
            "account": {"type": "link", "target": "Account"},
            "total": {"type": "data", "data_type": "number",
                      "derived": {"sum": ["amount", "amount"]}}}}}

    def test_a_good_one_loads(self):
        validate_unusual_checks(self._types())

    @pytest.mark.parametrize("unusual, why", [
        ({"numbers": []}, "1 to 10 number fields"),
        ({"numbers": ["category"]}, "is not a number"),
        ({"numbers": ["amount"], "within": ["total"]}, "link or computed"),
        ({"numbers": ["amount"], "within": ["account"]}, "link or computed"),
        ({"numbers": ["salary"]}, "classified"),
        ({"numbers": ["amount"], "within": ["id"]}, "is the id"),
        ({"numbers": ["amount"], "within": ["amount"]}, "named twice"),
        ({"numbers": ["amount"], "within": ["nope"]}, "not a field"),
        ({"numbers": ["amount"], "mode": "x"}, "unknown key"),
    ])
    def test_one_that_could_not_be_made_is_refused(self, unusual, why):
        with pytest.raises(ValueError, match=why):
            validate_unusual_checks(self._types(**unusual))


class TestTheStore:
    def test_replaced_whole_and_expected_is_remembered_by_the_value(self, tmp_path):
        store = UnusualFlagStore(tmp_path / "unusual_flags.db")
        flags, total = find_unusual(_planted(), "id", ["amount"], ["category"])
        store.replace("Transaction", {"west": (flags, total)})
        assert {flag.record_id for flag in store.flags("Transaction")} >= set(WRONG_KIND)
        assert store.totals("Transaction") == {"west": total}

        store.decide("Transaction", "r10", "amount", 300.0, "expected", "ops")
        decided = {flag.record_id: flag.decision for flag in store.flags("Transaction")}
        assert decided["r10"] == "expected" and decided["r11"] is None

        # THE SAME VALUE STAYS DECIDED; A CHANGED ONE DOES NOT.
        rows = _planted()
        next(row for row in rows if row["id"] == "r10")["amount"] = 900.0
        store.replace("Transaction", {"west": find_unusual(rows, "id", ["amount"], ["category"])})
        assert {flag.record_id: flag.decision for flag in store.flags("Transaction")}[
            "r10"] is None

    def test_no_longer_unusual_is_no_longer_flagged(self, tmp_path):
        store = UnusualFlagStore(tmp_path / "unusual_flags.db")
        store.replace("Transaction", {"west": find_unusual(_planted(), "id", ["amount"],
                                                           ["category"])})
        store.replace("Transaction", {"west": find_unusual(_records(), "id", ["amount"],
                                                           ["category"])})
        assert not set(WRONG_KIND) & {flag.record_id for flag in store.flags("Transaction")}

    def test_none_and_empty_compartments_are_different(self, tmp_path):
        store = UnusualFlagStore(tmp_path / "unusual_flags.db")
        flags, total = find_unusual(_planted(), "id", ["amount"], ["category"])
        store.replace("Transaction", {None: (flags[:1], 1), "": (flags[1:2], 1)})
        assert sorted(map(repr, (flag.compartment for flag in store.flags("Transaction")))) == \
            ["''", "None"]

    def test_an_unknown_decision_is_refused(self, tmp_path):
        with pytest.raises(ValueError, match="one of expected, worth_a_look"):
            UnusualFlagStore(tmp_path / "u.db").decide("T", "r", "f", 1.0, "ignore", "ops")
