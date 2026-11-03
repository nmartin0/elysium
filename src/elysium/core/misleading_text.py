"""Text that a person reads as something it is not (ZOO-01, ZOO-05,
ZOO-07).

THIS IS THE OTHER HALF of core/invisible_text.py. There, characters
are present and unseen. Here they are perfectly visible and mean
something other than they appear to.

    MOJIBAKE        "Ã©tÃ©" is "été" read as Latin-1 and stored back
                    as UTF-8. Every later reader sees the mangled
                    form, the original is not recoverable from it
                    reliably, and a match against "été" fails.

    HOMOGLYPHS      "Аcme" with a CYRILLIC А renders identically to
                    "Acme" and is a different string. A join misses,
                    a duplicate check passes, and two customer records
                    that look the same stay separate for ever.

    HTML ENTITIES   "Tom &amp; Jerry" is a name that has been through
                    an HTML encoder and not back. It displays as
                    "Tom &amp; Jerry" in anything that is not a
                    browser, and sorts and matches that way too.

DECLARED, NEVER REPAIRED, and here that restraint matters more than
anywhere else in this module's neighbourhood. Mojibake can be
un-mangled, entities can be decoded, a Cyrillic А can be swapped for a
Latin one -- and every one of those is a GUESS about what somebody
meant. The 2024 VLDB evaluation of twelve automatic repair algorithms
found most introduce more errors than they remove. So this names what
it sees and stops.

FALSE POSITIVES ARE THE REAL RISK, more than in the invisible case: a
tag character is never legitimate, but "Москва" is an ordinary
Russian city and "Tom & Jerry" is an ordinary name. Every check below
is written to stay quiet on text that is simply not English.
"""

import re
import unicodedata

# The Latin-1 characters that mojibake produces in quantity: a UTF-8
# byte pair read one byte at a time. Ã, Â, â and the like leading
# another high character.
_MOJIBAKE = re.compile(r"[\u00c2-\u00c3\u00e2][\u0080-\u00bf]")

# A named or numeric HTML entity. Deliberately narrow: `&` alone is
# an ampersand, not an encoding.
_HTML_ENTITY = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});")

_LATIN = re.compile(r"[A-Za-z]")
_CONFUSABLE_SCRIPTS = ("CYRILLIC", "GREEK")


def _mixed_script_words(value: str) -> list[str]:
    """Words holding both Latin letters and a confusable script.

    WITHIN A WORD, not within the value: "Acme Москва" is two words in
    two scripts and is perfectly ordinary, while "Аcme" is one word
    pretending to be another. Checking the whole string would flag
    every bilingual address in the database.
    """
    suspicious = []
    for word in value.split():
        if not _LATIN.search(word):
            continue  # no Latin at all: not pretending to be Latin
        for character in word:
            if character.isalpha():
                try:
                    name = unicodedata.name(character)
                except ValueError:
                    continue
                if name.startswith(_CONFUSABLE_SCRIPTS):
                    suspicious.append(word)
                    break
    return suspicious


def misleading_text(value) -> list[str]:
    """What about this value reads as something it is not."""
    if not isinstance(value, str) or not value:
        return []
    problems = []
    if _MOJIBAKE.search(value):
        problems.append(
            "mojibake: UTF-8 bytes read as Latin-1 and stored back, so "
            "the accented characters are mangled"
        )
    for word in _mixed_script_words(value):
        problems.append(
            f"{word!r} mixes Latin letters with another script, so it "
            f"renders like a Latin word and is a different string"
        )
    if _HTML_ENTITY.search(value):
        problems.append(
            "an HTML entity, so this text has been through an encoder "
            "and not back"
        )
    return problems


def describe_misleading(value) -> "str | None":
    """One sentence about how this value misleads, or None."""
    problems = misleading_text(value)
    if not problems:
        return None
    return f"{value!r} " + "; ".join(problems)
