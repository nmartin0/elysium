"""
A field can declare that its text is not pretending to be something
else (ZOO-01, ZOO-05, ZOO-06, ZOO-07).

THE OTHER HALF of the invisible-character rule. There, characters are
present and unseen. Here they are perfectly visible and mean
something other than they appear to.

    MOJIBAKE      "Ã©tÃ©" is "été" read as Latin-1 and written back as
                  UTF-8. Every later reader sees the mangled form and
                  a match against "été" fails.

    HOMOGLYPHS    "Аcme" with a CYRILLIC А renders identically to
                  "Acme" and is a different string. A join misses, a
                  duplicate check passes, and two records that look
                  the same stay separate for ever.

    ENTITIES      "Tom &amp; Jerry" has been through an HTML encoder
                  and not back. It displays that way in anything that
                  is not a browser, and sorts and matches that way.

ZOO-06 WENT WITH THE INVISIBLE ONES INSTEAD, where it belongs: a C0
control has no glyph, and ESC begins a terminal escape sequence --
text that repaints somebody's screen when they cat a log. Tab,
newline and carriage return stay allowed, for the same reason they
are allowed everywhere else here.

DECLARED, NEVER REPAIRED, and the restraint matters more here than
anywhere. Mojibake can be un-mangled, entities decoded, a Cyrillic А
swapped -- and every one is a GUESS about what somebody meant. The
2024 VLDB evaluation of twelve automatic repair algorithms found most
introduce more errors than they remove.

FALSE POSITIVES ARE THE REAL RISK. A tag character is never
legitimate, but "Москва" is an ordinary city and "Tom & Jerry" is an
ordinary name. Most of the tests below are about staying quiet.
"""

import pytest

from core.invisible_text import describe
from core.misleading_text import describe_misleading, misleading_text
from core.ontology.constraints import violation

DECLARED = {"data_type": "string",
             "constraints": {"no_misleading_text": True}}
INVISIBLE = {"data_type": "string",
              "constraints": {"no_invisible_characters": True}}


class TestWhatItCatches:
    @pytest.mark.parametrize("value", ["Ã©tÃ© 2024", "Ã¨re", "Â£40"])
    def test_mojibake(self, value):
        assert any("mojibake" in problem for problem in misleading_text(value))

    def test_a_cyrillic_homoglyph(self):
        assert misleading_text("\u0410cme Ltd")

    def test_a_greek_homoglyph(self):
        """Greek Ο and Latin O are the same shape too."""
        assert misleading_text("C\u039fMPANY")

    @pytest.mark.parametrize("value", ["Tom &amp; Jerry", "caf&#233;",
                                        "a &#x27; b"])
    def test_an_html_entity(self, value):
        assert any("entity" in problem for problem in misleading_text(value))

    def test_the_message_quotes_the_value(self):
        """A report naming a problem without the text is a report
        nobody can act on."""
        assert "Аcme" in describe_misleading("\u0410cme Ltd")


class TestWhatItLeavesAlone:
    @pytest.mark.parametrize("value", [
        "été 2024",             # real accents
        "Москва",               # all Cyrillic
        "Acme Москва",          # two words, two scripts
        "Tom & Jerry",          # a plain ampersand
        "α + β = γ",            # Greek maths
        "ada@example.com",
        "Acme Ltd",
        "R&D",
        "AT&T",
        "",
    ])
    def test_it_stays_quiet(self, value):
        assert misleading_text(value) == []

    def test_a_word_in_one_script_is_fine_however_unusual(self):
        """The check is MIXED script within a WORD. A word that is
        entirely Cyrillic is a word, not a disguise."""
        assert misleading_text("Привет мир") == []

    def test_a_non_string_is_not_examined(self):
        assert misleading_text(42) == []
        assert misleading_text(None) == []


class TestControlCharactersGoWithTheInvisibleOnes:
    @pytest.mark.parametrize("value", ["Acme\x1b[31m Ltd", "Acme\x00Ltd",
                                        "Acme\x07"])
    def test_a_control_character_is_invisible_not_misleading(self, value):
        assert describe(value) is not None

    @pytest.mark.parametrize("value", ["line one\nline two", "a\tb", "a\r\nb"])
    def test_layout_characters_still_pass(self, value):
        """Flagging these would catch half the addresses in any
        database."""
        assert describe(value) is None


class TestTheDeclaredRule:
    def test_a_violation_is_reported(self):
        assert violation(DECLARED, "\u0410cme") is not None

    def test_ordinary_text_passes(self):
        assert violation(DECLARED, "Acme Ltd") is None

    def test_a_field_that_does_NOT_declare_it_is_unaffected(self):
        """Opt-in, like its sibling. A deployment that says nothing
        sees no change."""
        assert violation({"data_type": "string"}, "\u0410cme") is None

    def test_the_two_rules_are_independent(self):
        """A deployment may well want to quarantine a smuggled
        instruction while only warning about an entity somebody forgot
        to decode."""
        smuggled = "Acme" + "".join(chr(0xE0000 + ord(c)) for c in "HI")

        assert violation(INVISIBLE, smuggled) is not None
        assert violation(DECLARED, smuggled) is None
        assert violation(DECLARED, "Tom &amp; Jerry") is not None
        assert violation(INVISIBLE, "Tom &amp; Jerry") is None
