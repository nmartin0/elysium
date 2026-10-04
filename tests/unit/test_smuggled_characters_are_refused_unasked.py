"""
Tag characters and bidi controls are refused without a deployment
asking. Zero-width is not.

NEW-6: `no_invisible_characters` was opt-in per field, so a deployment
that did not know to ask got no protection -- and not knowing to ask
is exactly the condition that makes a deployment vulnerable. The
owner's blocker was whether a default-on rule that can quarantine rows
is acceptable, given it changes what an existing deployment accepts.

THE ANSWER IS TO MAKE THE DEFAULT NARROW, which is what the compilers
did. GCC 12 ships `-Wbidi-chars=unpaired` as the DEFAULT, not `any`;
Rust warns by default. Both after CVE-2021-42574, Trojan Source, where
bidi controls make source "display differently than the actual
execution".

AND THE SPLIT IS NOT MINE EITHER. Tools that scan for these treat
bidi controls as "worth flagging even in small numbers", while general
invisible characters need a threshold -- "10+ consecutive invisible
code points → likely an encoded payload, not normal text" -- precisely
because emoji ZWJ sequences, the BOM, and Arabic and Hebrew text are
legitimate.

SO TWO FAMILIES BY DEFAULT:

    tag characters (U+E0000-E007F)   a full ASCII alphabet with no
                                     glyph -- the smuggling channel
    bidi controls (U+202A-202E,      reorder what follows, so
                   U+2066-2069)      "\\u202eDTL" renders as "LTD"

    zero-width                       NOT by default: it breaks string
                                     equality rather than hiding a
                                     message, and emoji need it

WHAT IT COSTS AN EXISTING DEPLOYMENT: a row whose text holds a
character from the first two families stops being accepted. That is
the intended change, it is narrow, and a field with a real reason can
declare `allow_invisible_characters`.
"""

import pytest

from core.invisible_text import dangerous_characters, describe_dangerous
from core.ontology.constraints import violation

PLAIN = {"data_type": "string"}
TAGS = "\U000E0041\U000E0042\U000E0043"
OVERRIDE = "\u202e"


class TestRefusedWithoutBeingAsked:
    def test_tag_characters(self):
        """THE SMUGGLING CHANNEL. A complete sentence hides inside a
        company name, and the agent reads what nobody can see."""
        assert violation(PLAIN, f"Acme Ltd{TAGS}") is not None

    def test_a_bidirectional_override(self):
        """Trojan Source, CVE-2021-42574. The characters are real and
        the reading is a lie."""
        assert violation(PLAIN, f"{OVERRIDE}DTL emcA") is not None

    def test_the_message_names_what_is_hiding(self):
        """A person deciding what to do about a row needs to know what
        is in it, not that something is."""
        message = violation(PLAIN, f"Acme Ltd{TAGS}")

        assert "tag character" in message

    def test_a_single_one_is_enough(self):
        """No threshold for these two families -- "worth flagging even
        in small numbers"."""
        assert violation(PLAIN, f"Acme{OVERRIDE}") is not None


class TestNotRefusedByDefault:
    """The half that keeps this narrow enough to turn on."""

    def test_zero_width_on_an_undeclared_field(self):
        assert violation(PLAIN, "Ac\u200bme Ltd") is None

    def test_an_emoji_sequence(self):
        """Zero-width joiners are how emoji families are built."""
        assert violation(PLAIN, "\U0001f468\u200d\U0001f469\u200d\U0001f467") is None

    @pytest.mark.parametrize("value", [
        "\u0645\u0631\u062d\u0628\u0627",            # Arabic
        "\u05e9\u05dc\u05d5\u05dd",                   # Hebrew
        "Acme Ltd", "", "  spaced  ", "Ünïcödé Ltd",
    ])
    def test_real_text_is_untouched(self, value):
        assert violation(PLAIN, value) is None

    def test_a_non_string_is_not_examined(self):
        assert violation({"data_type": "integer"}, 42) is None


class TestTheOptOut:
    def test_a_field_may_allow_them(self):
        """A deployment with a real reason says so, rather than having
        no way to."""
        allowed = {"data_type": "string",
                   "constraints": {"allow_invisible_characters": True}}

        assert violation(allowed, f"Acme Ltd{TAGS}") is None

    def test_opting_out_does_not_disable_the_declared_rule(self):
        """Two different switches. A field that asks for the strict
        rule gets it."""
        both = {"data_type": "string",
                "constraints": {"no_invisible_characters": True}}

        assert violation(both, "Ac\u200bme") is not None


class TestTheTwoDetectorsAgree:
    def test_dangerous_is_a_subset_of_invisible(self):
        """Filtered by family rather than recomputed, so the two can
        never disagree about what is PRESENT -- only about what is
        acceptable."""
        from core.invisible_text import invisible_characters

        value = f"Ac\u200bme{OVERRIDE}Ltd{TAGS}"
        every = invisible_characters(value)
        dangerous = dangerous_characters(value)

        assert set(dangerous) <= set(every)
        assert len(dangerous) < len(every)

    def test_describe_returns_none_for_clean_text(self):
        assert describe_dangerous("Acme Ltd") is None

    def test_describe_counts_them(self):
        message = describe_dangerous(f"Acme{TAGS}")

        assert "3 character(s)" in message


class TestItRunsWhereNoConstraintsAreDeclared:
    """THE WHOLE POINT, and the bug in my first attempt: `violation`
    returned early when a field had no constraints block, so the field
    with NO protection declared was the one the check never reached."""

    def test_a_field_with_no_constraints_block_is_still_checked(self):
        assert "constraints" not in PLAIN

        assert violation(PLAIN, f"Acme{TAGS}") is not None

    def test_a_field_with_an_empty_constraints_block_is_checked(self):
        empty = {"data_type": "string", "constraints": {}}

        assert violation(empty, f"Acme{TAGS}") is not None
