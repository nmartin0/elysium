"""A set, as a CSV somebody opens in a spreadsheet.

WHY THIS IS A MODULE AND NOT THREE LINES IN A ROUTE. A CSV handed to a
spreadsheet is CODE unless something stops it, and the thing that stops
it has to run on every cell of every export. One place deciding what a
cell may contain is the only arrangement where that is checkable.

THE PROJECT'S OWN AUDIT PREDICTED THIS FILE. `AUDIT_CHECKLIST.csv`
R35, "export-time formula escaping": "NOT APPLICABLE YET, verified:
there is no CSV or spreadsheet export anywhere in api/ or ui/. Nothing
produces a file a formula could execute in. Becomes live the moment an
export is built, and should be built WITH the escaping rather than
after." This is that moment.

WHAT THE ATTACK IS. A cell beginning `=`, `+`, `-` or `@` is a FORMULA
to Excel, LibreOffice and Google Sheets. `=cmd|' /c calc'!A1` in a
customer's name field becomes a command the moment somebody exports
the set and double-clicks the file -- on THEIR machine, with THEIR
privileges, from data a stranger typed into a form. The export is the
delivery mechanism and the spreadsheet is the vulnerability; neither
is ours to fix, so the escaping is.

OWASP'S GUIDANCE, FOLLOWED RATHER THAN INVENTED
(https://owasp.org/www-community/attacks/CSV_Injection). It names the
dangerous leading characters as equals, plus, minus and at-sign, "plus
tab, carriage return and line feed, plus full-width variants like
FULLWIDTH EQUALS SIGN and FULLWIDTH PLUS SIGN", and gives three steps
per field: "Wrap each cell field in double quotes", "Prepend each cell
field with a single quote", "Escape every double quote using an
additional double quote".

AND ITS CAVEAT, WHICH IS WHY THE PREFIX IS NOT OPTIONAL: "The above
techniques are not reliable in Microsoft Excel after saving and
re-opening the CSV file." Quoting ALONE does not stop evaluation --
Excel parses `"=1+1"` out of a CSV and evaluates it. The prefix is the
part that works; the quoting is for the comma, not the formula.

IT CHANGES THE VALUE, AND THAT IS SAID OUT LOUD RATHER THAN HIDDEN. A
name of `-Smith` exports as `'-Smith`, and most spreadsheets show it
as `-Smith` because a leading apostrophe is their own "treat as text"
marker -- but not all of them, and not always. A visibly altered cell
in a thousand is the price of none of them executing, and a reader who
can see the apostrophe can reason about it. A silently executed one
they cannot.

ONLY THE LEADING CHARACTER MATTERS. `A=B` is not a formula; `=A1` is.
Escaping every occurrence would mangle ordinary text -- email
addresses, negative numbers mid-sentence, hyphenated names -- for no
gain, which is how an escaping rule becomes one somebody turns off.
"""

import csv
import io
import re
from typing import Any

# WHAT MAKES A CELL A FORMULA, from OWASP's own list.
#
# THE WHITESPACE ONES ARE NOT DECORATION. A leading tab or carriage
# return is stripped by the spreadsheet before it decides what the cell
# is, so "\t=cmd" is a formula with a disguise -- which is exactly the
# shape a filter looking only for "=" would pass.
#
# THE FULL-WIDTH VARIANTS likewise: U+FF1D and U+FF0B are normalised to
# their ASCII forms by some locales' spreadsheet software, and a rule
# that cannot see them is one an attacker picks on purpose.
RISKY_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋")

# WHAT A PREFIXED CELL IS PREFIXED WITH. A single quote, which every
# major spreadsheet reads as "the rest of this is text".
TEXT_MARKER = "'"


# WHAT A SPREADSHEET WOULD READ AS A PLAIN NUMBER.
#
# A LEADING MINUS IS ON OWASP'S LIST because of `-2+3+cmd|' /c
# calc'!A1`, not because of `-20`. Prefixing every negative number
# would be strictly safe and quietly useless: Excel reads `'-20` as
# TEXT, so a SUM over an amount column silently skips every refund --
# and a financial export whose totals are wrong is worse than no
# export, because it looks right.
#
# Seen on the dev deployment the first time this ran: a refund of -20
# exported as `'-20.000000000`.
#
# A REGEX RATHER THAN float(), which accepts spellings a spreadsheet
# does not: `float("-1_0")` is -10.0 in Python and `-1_0` is text in
# Excel, so trusting it would call a non-number a number.
_PLAIN_NUMBER = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


def escape_cell(value: Any) -> str:
    """One cell, safe to hand a spreadsheet.

    NONE BECOMES EMPTY, not the word "None". A missing value and the
    string "None" are different facts, and a CSV has exactly one way to
    say the first.

    WHAT THIS DOES NOT DO is distinguish a value the caller may not
    read from a value that is genuinely absent -- DEV_UI.md 9.7's
    fourth state. A CSV has no tag to render, so the export omits the
    COLUMN for a field the caller cannot read rather than filling it
    with blanks that mean two different things. That decision is the
    caller's to make and lives in the route; this function only ever
    sees cells it is allowed to write.
    """
    if value is None:
        return ""
    text = str(value)
    # A NUMBER IS NOT A FORMULA, however it starts. See _PLAIN_NUMBER.
    if _PLAIN_NUMBER.match(text):
        return text
    if text.startswith(RISKY_PREFIXES):
        return TEXT_MARKER + text
    return text


def to_csv(columns: list[str], rows: list[dict]) -> str:
    """A set as CSV text, every cell escaped.

    QUOTE_ALL RATHER THAN QUOTE_MINIMAL, because the decision of which
    cells are "special enough" to quote is exactly the decision this
    module exists to take out of anybody's hands. Quoting everything
    costs bytes and removes a class of question.

    CRLF, which RFC 4180 specifies and Excel expects. Python's csv
    module writes it when told; the caller should not have to know.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    # THE HEADER IS ESCAPED TOO. Column names come from a deployment's
    # own ontology, which is configuration rather than user input --
    # but a field named `-rate` would still be a formula, and a rule
    # with an exception is a rule somebody has to remember.
    writer.writerow([escape_cell(column) for column in columns])
    for row in rows:
        writer.writerow([escape_cell(row.get(column)) for column in columns])
    return buffer.getvalue()


def filename_for(object_type: str, when: str) -> str:
    """What the browser should call the file.

    THE TYPE AND THE INSTANT, because somebody exporting the same set
    twice in a morning needs to tell the two apart, and a live set's
    membership is only true as of when it was taken.

    SANITISED TO A KNOWN ALPHABET rather than escaped. This string ends
    up in a `Content-Disposition` header, where a quote or a newline is
    header injection; an object type comes from the deployment's own
    configuration, so this cannot be reached by a stranger today, and
    that is an argument for it being cheap rather than for skipping it.
    """
    safe = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in object_type
    ) or "objects"
    stamp = "".join(
        character for character in when
        if character.isalnum() or character in "-_"
    )
    return f"{safe}-{stamp}.csv"
