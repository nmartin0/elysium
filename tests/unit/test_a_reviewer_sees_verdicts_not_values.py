"""
A merge reviewer is told whether two fields agree, not what they say.

THE PROBLEM, which is a security design rather than a UI preference:

    A REVIEWER MAY NOT BE CLEARED TO SEE THE FIELDS THAT DECIDE THE
    MATCH. Elysium is MAC-governed; the person best placed to judge
    whether two customers are the same may not be permitted to read
    the email address that settles it.

THE ANSWER HAS A LITERATURE AND IS NOT OURS. Privacy-preserving record
linkage calls it MASKED CLERICAL REVIEW: systems "that conceal the
plaintext by default, present categorical value frequencies, and
gradually disclose selected information", giving the reviewer "merely
selected plaintext based on the information whether an attribute pair
is equal, dissimilar, or somewhat similar".

It fits because it is the shape of the decision anyway.
`FUSION_AND_IDENTITY.md` already says "the reviewer's decision is made
on the agreement PATTERN, not the score", and `Candidate` already
carries `agreement: dict[str, bool]` -- the verdict without the value.

THE REQUIREMENT THAT DECIDES HOW THIS IS WRITTEN:

    The facility responsible for the (masked) clerical review should
    only have access to those plaintext attributes that are displayed.

So a masked comparison does not carry hidden values and mark them
hidden. IT NEVER HOLDS THEM. The difference is invisible on a rendered
screen and total in a log, a cache, an error report or a future
refactor -- the rule `core/notifications.py` already states:
"filtering-after-assembly is where these systems leak, because the
unfiltered thing existed".

NOT BUILT: the screen. This is its backend half, tested and unused,
with a removal condition in the vulture whitelist.
"""

import pytest

from core.masked_review import (
    AGREE,
    DIFFER,
    ONE_SIDE_MISSING,
    agreement_pattern,
    masked_comparison,
    withheld_fields,
)

AGREEMENT = {"name": True, "email": True, "postcode": False}
LEFT = {"name": "Ada Okafor", "email": "a@x.com", "postcode": "SW1"}
RIGHT = {"name": "Ada Okafor", "email": "a@x.com", "postcode": "E14"}


class TestTheVerdictIsAlwaysGiven:
    def test_every_compared_field_has_one(self):
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, [])

        assert [e["field"] for e in entries] == ["name", "email", "postcode"]
        assert all("verdict" in e for e in entries)

    def test_agreement_and_disagreement_are_named(self):
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, [])
        verdicts = {e["field"]: e["verdict"] for e in entries}

        assert verdicts["email"] == AGREE
        assert verdicts["postcode"] == DIFFER

    def test_a_missing_side_is_its_own_verdict(self):
        """"Differ" would be a lie: nothing disagreed, one record had
        nothing to say.

        READABLE, WHICH THIS DID NOT SAY AND HAD TO. It passed `[]` for
        the readable fields, so the field under test was WITHHELD --
        and "the reviewer may not see this" is a different fact from
        "one record lacks it". The old verdict could not tell them
        apart, which is exactly the defect; asserting the right answer
        from the wrong setup is how that survived.
        """
        entries = masked_comparison({"email": False}, {"email": "a@x.com"},
                                     {}, ["email"])

        assert entries[0]["verdict"] == ONE_SIDE_MISSING

    def test_A_WITHHELD_FIELD_IS_NOT_CALLED_MISSING(self):
        """THE DEFECT, AS A TEST. The route fetches only readable
        fields, so an unreadable one is absent from both rows -- and a
        verdict reading key presence called that "one side missing".
        A reviewer deciding whether two records are the same person
        was told one of them lacked a field that it has, about data
        they were not cleared to see.

        WHAT THEY GET INSTEAD is the matcher's own verdict, which is
        this module's whole premise: a reviewer can be told two emails
        agree without being shown either. Nothing further is
        disclosed -- the verdict was always going to be shown.
        """
        # THE ROWS DO NOT HOLD THE FIELD, which is what the route
        # actually produces: it fetches `readable & agreement`, so an
        # unreadable field is never requested and never arrives. A
        # first version of this test handed the rows values anyway and
        # passed with the fix REVERTED -- the presence check was
        # satisfied for a reason the real caller never supplies.
        entries = masked_comparison({"email": False}, {}, {}, [])

        assert entries[0]["verdict"] == DIFFER
        assert entries[0]["readable"] is False
        assert "left" not in entries[0] and "right" not in entries[0]

    def test_and_a_readable_field_that_is_NULL_ON_BOTH_SIDES_is_missing(self):
        """THE THIRD OF THE THREE, and the one the old key check could
        never reach: `get_object` returns a key for every field it is
        ASKED for, so a requested field's key was always present and
        this verdict never fired for a readable field at all. It fires
        on the VALUE now, which is the fact it names."""
        entries = masked_comparison({"email": True}, {"email": None},
                                     {"email": None}, ["email"])

        assert entries[0]["verdict"] == ONE_SIDE_MISSING
        assert entries[0]["readable"] is True
        # AND NO NULL ON THE WIRE. The verdict already says the side
        # was empty; a serialised None would sit in anything that
        # cached the response.
        assert "left" not in entries[0] and "right" not in entries[0]


class TestWhatIsWithheldIsABSENT:
    def test_an_unreadable_field_carries_no_value_at_all(self):
        """THE REQUIREMENT. Not None, not a sentinel, not a masked
        string -- absent. A caller cannot render, log or serialise what
        was never put in the structure."""
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, ["name"])
        email = next(e for e in entries if e["field"] == "email")

        assert "left" not in email
        assert "right" not in email
        # `readable` SAYS WHY THE VALUE IS ABSENT and carries no part
        # of it. Absence alone cannot distinguish "withheld" from
        # "null on both sides", and `withheld_fields` was reading it
        # as the first.
        assert set(email) == {"field", "verdict", "readable"}
        assert email["readable"] is False

    def test_a_readable_field_carries_both_values(self):
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, ["name"])
        name = next(e for e in entries if e["field"] == "name")

        assert name["left"] == "Ada Okafor"
        assert name["right"] == "Ada Okafor"

    def test_no_readable_fields_means_verdicts_only(self):
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, [])

        assert all(set(e) == {"field", "verdict", "readable"} for e in entries)
        assert all(e["readable"] is False for e in entries)

    def test_the_withheld_value_is_nowhere_in_the_output(self):
        """The strongest form of the check: the string itself does not
        appear, however the structure is walked."""
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, ["name"])

        assert "a@x.com" not in repr(entries)
        assert "SW1" not in repr(entries)


class TestWhatTheReviewerDecidesOn:
    def test_the_pattern_is_names_and_verdicts(self):
        """"The reviewer's decision is made on the agreement PATTERN,
        not the score" -- and "a number alone cannot be argued with"."""
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, [])

        assert agreement_pattern(entries) == (
            "name: agree, email: agree, postcode: differ")

    def test_the_pattern_never_holds_a_value(self):
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, ["name"])

        assert "Ada Okafor" not in agreement_pattern(entries)

    def test_what_was_judged_blind_is_recorded(self):
        """An approval made while three of five deciding fields were
        masked is a weaker artifact than one made with all five
        visible, and a later reader should be able to tell which they
        are holding."""
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT, ["name"])

        assert withheld_fields(entries) == ["email", "postcode"]

    def test_nothing_withheld_when_everything_is_readable(self):
        entries = masked_comparison(AGREEMENT, LEFT, RIGHT,
                                     ["name", "email", "postcode"])

        assert withheld_fields(entries) == []


class TestItDecidesNoAccessQuestion:
    def test_it_takes_the_readable_names_rather_than_a_user(self):
        """The same lesson as the change hints and the display check: a
        second place deciding one security question is how two rules
        drift apart."""
        import inspect

        parameters = list(inspect.signature(masked_comparison).parameters)

        assert parameters == ["agreement", "left_row", "right_row",
                               "readable_fields"]

    def test_the_module_imports_nothing_from_core(self):
        from pathlib import Path

        source = Path("core/masked_review.py").read_text()
        imports = [line for line in source.splitlines()
                   if line.startswith(("import ", "from "))]

        assert not [line for line in imports if "core." in line], imports


class TestFieldsOutsideTheDecision:
    def test_a_field_not_compared_is_not_shown(self):
        """Showing it would invite a reviewer to weigh something the
        score did not."""
        entries = masked_comparison({"name": True},
                                     {"name": "Ada", "secret": "x"},
                                     {"name": "Ada", "secret": "y"},
                                     ["name", "secret"])

        assert [e["field"] for e in entries] == ["name"]

    @pytest.mark.parametrize("agreement", [None, {}])
    def test_nothing_compared_yields_nothing(self, agreement):
        assert masked_comparison(agreement, LEFT, RIGHT, ["name"]) == []
