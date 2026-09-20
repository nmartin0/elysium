"""
A condition on how many objects match, per recipient.

WHAT THIS IS NOT: a diff. It does not say WHICH objects appeared,
because that means storing last time's result set, and no alerting
system worth copying does.

Databricks stores state -- alerts "resolve to OK, TRIGGERED, or
ERROR". Google Cloud compares "the number of rows in the query result"
against a threshold over a lookback window. The canonical
change-detection pattern is a saved watermark. All keep a number or a
flag; none keeps the answer.

WHICH MAKES PER-RECIPIENT EVALUATION FREE. Each person's previous
RESULT SET would be tens of thousands of ids times however many
recipients; an integer each is nothing, and it is all a "3 more than
last time" notification needs.

AND THERE IS NO PRIVILEGED NUMBER. Each count comes from that
person's own search, compared to their own history. Nobody computes
one figure and redacts it, because no such figure exists.
"""

import pytest

from core.count_condition import (
    CountCondition,
    _verdict,
    evaluate_for_recipients,
)


@pytest.fixture
def store(tmp_path):
    from core.notifications import NotificationStore

    return NotificationStore(tmp_path / "n.db")


ABOVE_TEN = CountCondition("tickets", "Open tickets", above=10)
GAINED_THREE = CountCondition("txns", "New transactions", gained=3)


class TestTheFirstEvaluationIsABaseline:
    def test_it_says_nothing(self):
        """A CONDITION DECLARED TODAY has no previous count, and
        treating that as zero would report every existing match as a
        gain -- the flood a monitoring tool that hit it warns about:
        "the first successful run creates a baseline, never a flood of
        fake new ads"."""
        assert _verdict(ABOVE_TEN, None, 15) is None
        assert _verdict(GAINED_THREE, None, 900) is None

    def test_but_it_records_the_count(self, store):
        evaluate_for_recipients(ABOVE_TEN, {"alice": 15}, store)

        assert store.last_count("tickets", "alice") == 15

    def test_so_the_second_evaluation_can_speak(self, store):
        evaluate_for_recipients(ABOVE_TEN, {"alice": 5}, store)

        assert evaluate_for_recipients(ABOVE_TEN, {"alice": 15}, store) == 1


class TestCrossingAThreshold:
    def test_rising_past_it_fires(self):
        assert "above 10" in _verdict(ABOVE_TEN, 8, 15)

    def test_staying_below_says_nothing(self):
        assert _verdict(ABOVE_TEN, 8, 9) is None

    def test_a_changed_count_while_above_is_news(self):
        assert "still above" in _verdict(ABOVE_TEN, 15, 18)

    def test_an_unchanged_count_while_above_is_not(self):
        """A THRESHOLD REPORTING EVERY EVALUATION while the count
        stays high is a channel nobody reads by the time it
        matters."""
        assert _verdict(ABOVE_TEN, 15, 15) is None


class TestGaining:
    def test_gaining_enough_fires(self):
        assert "4 more" in _verdict(GAINED_THREE, 5, 9)

    def test_gaining_too_few_says_nothing(self):
        assert _verdict(GAINED_THREE, 5, 6) is None


class TestFallingIsNotReported:
    def test_a_count_that_dropped_says_nothing(self):
        """AN OBJECT LEAVING A FILTERED SET may mean it changed, was
        deleted, or that the reader's grants changed -- and the third
        is indistinguishable from the first two with what is stored
        here.

        A monitoring tool puts the same caution plainly: a row
        "disappearing from a result list never becomes
        AD_BECAME_INACTIVE".
        """
        assert _verdict(ABOVE_TEN, 15, 5) is None
        assert _verdict(GAINED_THREE, 9, 5) is None


class TestPerRecipient:
    def test_each_person_is_compared_to_their_own_history(self, store):
        """NO PRIVILEGED NUMBER. Alice and Bob see different counts
        because they searched with different authority, and each is
        measured against what THEY saw last time."""
        evaluate_for_recipients(GAINED_THREE, {"alice": 10, "bob": 1}, store)

        told = evaluate_for_recipients(
            GAINED_THREE, {"alice": 20, "bob": 2}, store,
        )

        assert told == 1
        # TWO FOR ALICE: the "now watching" notice from the baseline
        # evaluation, plus this one. Bob has only his watching notice,
        # because gaining 1 is not gaining 3.
        alice = [n.kind for n in store.for_user("alice")]
        bob = [n.kind for n in store.for_user("bob")]

        assert alice.count("count_condition") == 1
        assert bob.count("count_condition") == 0

    def test_a_newcomer_gets_a_baseline_not_a_flood(self, store):
        """SOMEBODY GRANTED ACCESS TODAY has no history, so their
        first evaluation is a baseline even though the condition has
        been firing for others for weeks."""
        evaluate_for_recipients(ABOVE_TEN, {"alice": 5}, store)
        evaluate_for_recipients(ABOVE_TEN, {"alice": 15}, store)

        told = evaluate_for_recipients(
            ABOVE_TEN, {"alice": 15, "newcomer": 15}, store,
        )

        assert told == 0


class TestTheBaselineIsAnnounced:
    def test_a_first_evaluation_says_it_is_watching(self, store):
        """SILENCE IS INDISTINGUISHABLE FROM A CONDITION THAT NEVER
        RAN. Somebody who declares one and hears nothing cannot tell
        "watching, nothing to report" from "broken"."""
        evaluate_for_recipients(ABOVE_TEN, {"alice": 15}, store)

        kinds = [n.kind for n in store.for_user("alice")]

        assert kinds == ["count_condition_watching"]

    def test_it_is_not_an_alert(self, store):
        """RETURNS ZERO TOLD. A baseline is information, not a
        condition being met, and a caller counting alerts must not
        count it."""
        assert evaluate_for_recipients(ABOVE_TEN, {"alice": 15}, store) == 0

    def test_it_happens_once(self, store):
        """ONCE PER PERSON PER CONDITION BY CONSTRUCTION, because
        there is no second first time."""
        evaluate_for_recipients(ABOVE_TEN, {"alice": 15}, store)
        evaluate_for_recipients(ABOVE_TEN, {"alice": 16}, store)

        watching = [
            n for n in store.for_user("alice")
            if n.kind == "count_condition_watching"
        ]

        assert len(watching) == 1


class TestAConfigurationChangeResetsTheBaseline:
    def test_a_count_is_not_compared_across_one(self, store):
        """A COUNT IS A FACT ABOUT WHAT ONE PERSON COULD SEE, and what
        a person can see is decided by policy.yaml -- which
        `source_digest` covers.

        Somebody granted a new region sees more objects without
        anything having been added.
        """
        evaluate_for_recipients(GAINED_THREE, {"alice": 5}, store, "digest-1")

        told = evaluate_for_recipients(
            GAINED_THREE, {"alice": 50}, store, "digest-2",
        )

        assert told == 0

    def test_but_the_next_one_compares_normally(self, store):
        """THE RESET IS ONE EVALUATION, not a permanent silence. Once
        a count has been taken under the new configuration, the
        following one is comparable with it."""
        evaluate_for_recipients(GAINED_THREE, {"alice": 5}, store, "digest-1")
        evaluate_for_recipients(GAINED_THREE, {"alice": 50}, store, "digest-2")

        told = evaluate_for_recipients(
            GAINED_THREE, {"alice": 60}, store, "digest-2",
        )

        assert told == 1

    def test_it_guards_both_directions(self, store):
        """A GRANT CHANGE MOVES A COUNT EITHER WAY. Somebody who LOST
        a region sees fewer without anything having been removed, and
        a guard that only covered falls would report that as data
        leaving."""
        falling = CountCondition("k", "Open tickets", fell=3)
        evaluate_for_recipients(falling, {"alice": 50}, store, "digest-1")

        told = evaluate_for_recipients(
            falling, {"alice": 5}, store, "digest-2",
        )

        assert told == 0


class TestFallingCounts:
    def test_a_real_fall_is_reported(self, store):
        """SAFE ONLY BECAUSE THE CONFIGURATION IS PINNED. With the
        reader's authority identical, a drop means the data moved."""
        falling = CountCondition("k", "Open tickets", fell=3)
        evaluate_for_recipients(falling, {"alice": 9}, store, "d")

        told = evaluate_for_recipients(falling, {"alice": 5}, store, "d")

        assert told == 1

    def test_it_says_how_many_never_which(self, store):
        """KNOWING WHICH needs last time's result set, which is
        exactly what is not stored -- and that does not change."""
        falling = CountCondition("k", "Open tickets", fell=3)
        evaluate_for_recipients(falling, {"alice": 9}, store, "d")
        evaluate_for_recipients(falling, {"alice": 5}, store, "d")

        summary = [
            n.summary for n in store.for_user("alice")
            if n.kind == "count_condition"
        ][0]

        assert "4 fewer" in summary


class TestRepeatsAreSuppressed:
    def test_the_same_summary_is_not_sent_twice(self, store):
        evaluate_for_recipients(ABOVE_TEN, {"alice": 5}, store)
        evaluate_for_recipients(ABOVE_TEN, {"alice": 15}, store)

        # Back below, then across again to the same number.
        evaluate_for_recipients(ABOVE_TEN, {"alice": 5}, store)

        assert evaluate_for_recipients(ABOVE_TEN, {"alice": 15}, store) == 0


class TestTheCountAndTheSummaryCoexist:
    def test_notifying_does_not_wipe_the_count(self, store):
        """A REAL BUG, CAUGHT BY PROBING THE TWO TOGETHER. The state
        table's writer used INSERT OR REPLACE, which deletes the row
        and inserts a new one -- so recording a notification silently
        wiped the count, and the next evaluation compared against
        nothing.
        """
        store.record_count("k", "alice", 5)
        store.record_notified("k", "alice", "a summary")

        assert store.last_count("k", "alice") == 5

    def test_and_recording_a_count_does_not_wipe_the_summary(self, store):
        store.record_notified("k", "alice", "a summary")
        store.record_count("k", "alice", 9)

        assert store.already_notified("k", "alice", "a summary")
