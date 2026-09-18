"""
A drift headline that names one column when several are affected.

THE DETAIL WAS ALWAYS COMPLETE -- describe_drift names every drifted
column, with the offending value and the rows checked. Verified before
changing anything, and it is the reason this is a small fix rather
than the large one the roadmap recorded.

WHAT THE HEADLINE DID was name drift[0] alone. Someone reading it
fixes that column, re-runs, and discovers the next one a full read of
the customer's database later. Saying the count costs nothing.
"""

from core.mirror.drift_policy import verdict_for_type_change


class TestTheHeadline:
    def test_one_column_reads_naturally(self):
        detail = verdict_for_type_change("s", "t", "amount").detail

        assert "column 'amount' no longer holds" in detail
        assert "other column" not in detail

    def test_several_columns_say_how_many(self):
        detail = verdict_for_type_change("s", "t", "amount", also_affected=2).detail

        assert "and 2 other column(s)" in detail

    def test_the_verb_agrees(self):
        """"column 'a' and 2 others no longer HOLDS" reads as a
        mistake, and a message that reads as a mistake gets trusted
        less than one that does not."""
        one = verdict_for_type_change("s", "t", "a").detail
        many = verdict_for_type_change("s", "t", "a", also_affected=3).detail

        assert "holds the type" in one
        assert "hold the type" in many
        assert "holds the type" not in many

    def test_the_decision_is_unchanged(self):
        # REFUSED EITHER WAY. This commit changes the wording of a
        # refusal, not whether it happens -- a type change "reaches
        # every reader, where a removal's damage is confined to
        # writers".
        for affected in (0, 5):
            assert verdict_for_type_change("s", "t", "a", affected).absorbed is False
