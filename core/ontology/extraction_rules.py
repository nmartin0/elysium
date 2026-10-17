"""Rules that take a value OUT of free text (17 October).

    order_number:
      data_type: string          # or integer, decimal, date
      enrich:
        from: [body]
        instruction: The order number the customer refers to.
        extract: true

Choices (core/ontology/enriched_fields.py) answer "which of these?".
Extraction answers "what does the text say it is?" -- an order number,
an amount, a date -- and the answer is a piece of the text itself.

THE RULE LANGUAGE IS CONTEXT WORDS PLUS A FIXED SHAPE, which is what the
rule-based extraction systems that have lasted settled on. IBM's SystemT
builds every extractor from "basic character-level extraction
primitives, such as regular expressions or dictionaries" combined by
span predicates such as FollowsTok; spaCy's Matcher describes a value
token by token, and allows a regular expression only inside one token.
Here a rule says which words come first, and which of a few SHAPES the
value has:

    {"field": "body", "after": ["order number", "order no"],
     "within": 2, "take": "code"}

    "In body, after 'order number' or 'order no' (within 2 words),
     take a code."

THE MODEL NEVER WRITES A REGULAR EXPRESSION. The shapes' patterns are
written here, reviewed and tested, and a model can only choose among
them. Three findings decided it: models write regexes badly (GPT-3.5's
first answer was correct 33.6% of the time, Phi-1.5's 2.3% -- Siddiq
et al., ICSE 2024), worst at finding text inside text (o3-mini: 97% on
whole-string matches, 75% on partial ones -- arXiv 2503.20579); a
backtracking regex can stall a machine (Cloudflare, 2 July 2019: one
expression, every core, 27 minutes); and Python's `re` has no time limit
to bound it. spaCy's Matcher was measured as an alternative (17
October, spaCy 3.8.16): it returns every overlapping match -- one `*`
over 800 words gave 320,400 -- and two `*` over 800 words ran out of
memory under a 3 GB limit. With its wildcards removed, what was left
did not earn its 274 MB and 44 packages.

THE VALUE IS ALWAYS TEXT FROM THE ROW. A rule returns a span of its
input, never text of its own -- Google's LangExtract makes the same
promise ("every extracted entity is mapped back to its exact character
offsets in the source text"). Nothing can be invented, by a rule or by
the model labelling the sample (enrichment_compiler checks its answers
the same way).

TYPED THE WAY THE SYNC TYPES. An extracted number or date is converted
by field_types.coerce, through the source's declared locale (DEP-1) --
the one place Elysium already decides that `02/01/2024` is the second
of January in pt_BR and the first of February in en_US, refuses
two-digit years, and never guesses. A value that does not convert is
EMPTY, never repaired.

NOT YET, each for its own decision: dates relative to something
("tomorrow" needs a reference time -- Duckling is handed one; which of
a record's dates would it be?), times of day (a wall-clock reading or an
instant: timestamp or timestamptz), and dates or numbers written in
words ("12 March", "forty-two").

LINEAR, BOUNDED. The tokenizer's pattern has no nested choice to
backtrack into, every rule looks at most MAX_WITHIN words past its
phrase, and the input is what gold already holds.
"""

import re
from collections.abc import Mapping

#: What an extracted field may be, and the shapes a rule may take for it.
#: A shape is offered only where its text can become the field's type.
SHAPES_FOR = {
    "string": ("word", "words", "number", "code", "date"),
    "integer": ("number",),
    "decimal": ("number",),
    "date": ("date",),
}
SHAPE_WORDS = {
    "word": "a word",
    "words": "words",
    "number": "a number",
    "code": "a code",
    "date": "a date",
}

#: How far past its phrase a rule may look, in words.
MAX_WITHIN = 5
#: The most words `words` may take.
MAX_TAKE_WORDS = 6
#: The longest value a rule returns; a span past this is not a value.
MAX_VALUE_CHARS = 200

# ONE TOKEN: a run of word characters, which may be joined by - _ / . ,
# to the next run ("INV-2024-0012", "1,234.50", "2024-01-02",
# "12/03/2024"); or one other non-space character. Each joined group
# STARTS with its separator, so there is never a choice to go back to --
# the pattern cannot backtrack.
#
# A SIGN BELONGS TO ITS NUMBER: "-12" is one token when the sign starts
# a word and a digit follows. Without this, "a refund of -12" gave 12 --
# a value with its meaning reversed, found by its test.
_TOKEN = re.compile(r"(?:(?<!\w)[-+](?=\d))?\w+(?:[-_/.,]\w+)*|[^\w\s]", re.UNICODE)
_IS_WORD = re.compile(r"\w", re.UNICODE)

_SHAPE = {
    "word": re.compile(r"[^\W\d_]+", re.UNICODE),
    # A sign, digits, then digits with , or . between; ends in a digit.
    "number": re.compile(r"[-+]?\d+(?:[.,]\d+)*"),
    # Letters and digits joined by - _ / ., with at least one digit:
    # "INV-2024-0012", "A1234", "4412".
    "code": re.compile(r"(?=[^\d]*\d)[^\W_]+(?:[-_/.][^\W_]+)*", re.UNICODE),
    # ISO, or day/month/year in some order with a four-digit year:
    # which order is the declared locale's to say, not this pattern's.
    "date": re.compile(r"\d{4}-\d{2}-\d{2}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}"),
}


def tokens(text) -> list[tuple[str, int, int]]:
    """(text, start, end) for every token, in order."""
    if text is None:
        return []
    return [(match.group(), match.start(), match.end()) for match in _TOKEN.finditer(str(text))]


def phrase_words(phrase: str) -> list[str]:
    """A phrase as the casefolded word tokens it is matched by."""
    return [token.casefold() for token, _, _ in tokens(phrase) if _IS_WORD.search(token)]


def fits(shape: str, token: str) -> bool:
    return _SHAPE[shape].fullmatch(token) is not None


def take(rule: Mapping, text) -> "str | None":
    """The value one extraction rule finds in one input, or None.

    The phrase's every occurrence is tried, left to right; the first
    that has a value of the rule's shape within `within` words after it
    gives the answer. `words` takes consecutive words up to `max_words`,
    stopping at punctuation. The answer is the source's own text,
    exactly as written."""
    found = tokens(text)
    if not found:
        return None
    folded = [token.casefold() for token, _, _ in found]
    within, shape = rule["within"], rule["take"]
    for phrase in rule["after"]:
        wanted = phrase.split()
        width = len(wanted)
        for start in range(len(found) - width + 1):
            if folded[start:start + width] != wanted:
                continue
            value = _after(found, start + width, within, shape, rule.get("max_words", 1))
            if value is not None:
                return str(text)[value[0]:value[1]]
    return None


def _after(found, at: int, within: int, shape: str, max_words: int) -> "tuple[int, int] | None":
    looked = 0
    index = at
    while index < len(found) and looked < within:
        token, start, end = found[index]
        if not _IS_WORD.search(token):
            # PUNCTUATION IS PASSED OVER, not counted: "order number: 4412"
            # and "order number 4412" are the same distance.
            index += 1
            continue
        looked += 1
        if shape == "words":
            last = end
            taken = 1
            following = index + 1
            while (following < len(found) and taken < max_words
                   and _IS_WORD.search(found[following][0])):
                last = found[following][2]
                taken += 1
                following += 1
            return (start, last) if last - start <= MAX_VALUE_CHARS else None
        if fits(shape, token):
            return (start, end) if end - start <= MAX_VALUE_CHARS else None
        index += 1
    return None


def typed(text: "str | None", data_type: str, locale: "str | None"):
    """An extracted span as the field's type, or None if it is not one.

    Through field_types.coerce, as a synced value is: the same locale
    rules, the same refusals. A string is the span as written, its
    spacing tidied."""
    if text is None:
        return None
    if data_type == "string":
        return " ".join(text.split()) or None
    from core.ontology.field_types import coerce

    try:
        return coerce(text, data_type, locale=locale)
    except (ValueError, TypeError, ArithmeticError):
        return None


def same_value(left, right) -> bool:
    """Whether two extracted values say the same thing: equal as their
    type, and for text equal ignoring case and spacing."""
    if left is None or right is None:
        return False
    if isinstance(left, str) and isinstance(right, str):
        return " ".join(left.casefold().split()) == " ".join(right.casefold().split())
    return bool(left == right)


def describe(rule: Mapping) -> str:
    """One extraction rule in plain words, for the person approving it."""
    phrases = " or ".join(repr(phrase) for phrase in rule["after"])
    within = rule["within"]
    distance = "next word" if within == 1 else f"within {within} words"
    what = (f"up to {rule['max_words']} words" if rule["take"] == "words"
            else SHAPE_WORDS[rule["take"]])
    return f"In {rule['field']}, after {phrases} ({distance}), take {what}"
