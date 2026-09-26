"""Characters that are in the text but not on the screen (ZOO-02,
ZOO-03, ZOO-04).

THE PROBLEM, MEASURED. A customer name synced from a source:

    codepoints 26, visible 8

A person reviewing that row reads "Acme Ltd". The AGENT reads "Acme
Ltd" followed by eighteen Unicode TAG characters spelling out an
instruction, because tag characters have no glyph and every renderer
drops them. The same field, two different texts, and the one nobody
can see is the one the model acts on.

THREE FAMILIES, and they fail differently:

  TAG CHARACTERS (U+E0000-U+E007F) carry a full ASCII alphabet with
  no visual presence whatsoever. This is the smuggling channel: a
  complete sentence hides inside a company name.

  BIDI CONTROLS (U+202A-U+202E, U+2066-U+2069) REORDER what follows,
  so "\u202eDTL" renders as "LTD". The characters are real and the
  reading is a lie -- the Trojan Source attack, CVE-2021-42574.

  ZERO-WIDTH characters (U+200B-U+200D, U+FEFF) do not hide a
  message; they break equality. "Ac\u200bme" and "Acme" are different
  strings that look identical, so a join misses, a duplicate check
  passes, and a match_on rule quietly fails to match.

WHAT THIS MODULE DOES NOT DO: strip them. Removing characters from a
customer's data is a transformation nobody asked for, and this
project's rule is that cleaning is DECLARED, never inferred -- the
same rule that stopped the pipeline trimming the security field. What
it offers is a name for the thing, so a deployment can declare
`no_invisible_characters: true` on a field and choose, through the
existing policy, whether a violation warns, quarantines the row or
refuses the table.

NEWLINES AND TABS ARE NOT INVISIBLE in this sense. They have no glyph
either, but they are ordinary text that every reader renders as
layout, and standardisation already reasons about them explicitly.
"""

TAG_CHARACTERS = range(0xE0000, 0xE0080)
BIDI_CONTROLS = (
    0x202A, 0x202B, 0x202C, 0x202D, 0x202E,   # embedding and override
    0x2066, 0x2067, 0x2068, 0x2069,           # isolates
)
ZERO_WIDTH = (0x200B, 0x200C, 0x200D, 0xFEFF)


def invisible_characters(value) -> list[str]:
    """The names of the invisible characters in this value, in order.

    Names rather than codepoints, because a violation message is read
    by a person deciding what to do about a row, and "U+202E" tells
    them less than "a right-to-left override".
    """
    if not isinstance(value, str):
        return []
    found = []
    for character in value:
        point = ord(character)
        if point in TAG_CHARACTERS:
            found.append(f"a Unicode tag character (U+{point:04X})")
        elif point in BIDI_CONTROLS:
            found.append(f"a bidirectional control (U+{point:04X})")
        elif point in ZERO_WIDTH:
            found.append(f"a zero-width character (U+{point:04X})")
    return found


def describe(value) -> "str | None":
    """One sentence about what is hiding in this value, or None.

    THE COUNT IS THE POINT. A message naming one character when there
    are eighteen would let somebody fix the first and re-run, and the
    eighteen are the attack.
    """
    found = invisible_characters(value)
    if not found:
        return None
    visible = "".join(
        character for character in value
        if ord(character) not in TAG_CHARACTERS
        and ord(character) not in BIDI_CONTROLS
        and ord(character) not in ZERO_WIDTH
    )
    kinds = sorted(set(name.split(" (")[0] for name in found))
    return (
        f"reads as {visible!r} but holds {len(found)} invisible "
        f"character(s): {', '.join(kinds)}. A person reviewing this row "
        f"cannot see them; anything reading the text can."
    )
