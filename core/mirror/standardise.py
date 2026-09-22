"""Turning a source value into a canonical one WITHOUT changing what it
means -- silver's first step (GOLD-1, MEDALLION_PIPELINE.md's S1).

THE LINE THIS DRAWS, from the research: NFC normalisation and
whitespace cleanup are the recommended conservative baseline; case
folding and stripping accents are AGGRESSIVE and lose information --
case, punctuation and diacritics can carry meaning. So this module
changes only what cannot change an answer, and the aggressive
normalisations belong to gold's MATCH KEYS, as separate derived
columns, never replacing a value.

WHAT IS APPLIED TO EVERY STRING, unless a field opts out:

  unicode NFC   'cafe\u0301' and 'caf\u00e9' are the same word, and a
                filter for one must find the other. Composed form is
                the conventional storage choice.
  trim          leading and trailing whitespace is never meant.
  collapse      runs of internal whitespace become one space.

WHAT MUST BE DECLARED, because only the deployment knows it:

  null_if       the strings this source writes to mean "nothing":
                "N/A", "-", "unknown", "". A sentinel left as text is
                a value that sorts, matches and aggregates as though
                somebody wrote it down.

Every rule is per field. Nothing is inferred from the data.
"""

import unicodedata
from typing import Any

# Applied to strings unless the field declares standardise: false.
DEFAULTS: dict[str, Any] = {
    "unicode": "NFC",
    "trim": True,
    "collapse_whitespace": True,
    "null_if": (),
}

KNOWN_RULES = frozenset(DEFAULTS)
UNICODE_FORMS = frozenset({"NFC", "NFD", "NFKC", "NFKD"})


def rules_for(field_config: dict) -> dict[str, Any] | None:
    """One field's rules, or None when it opts out of standardisation.

    Raises on an unknown rule or an impossible value: a typo in a
    declared rule must fail at load, not silently do nothing.
    """
    declared = field_config.get("standardise", {})
    if declared is False:
        return None
    if not isinstance(declared, dict):
        raise ValueError(
            f"standardise must be a mapping of rules or false, got {declared!r}."
        )
    unknown = set(declared) - KNOWN_RULES
    if unknown:
        raise ValueError(
            f"unknown standardise rule(s) {sorted(unknown)} -- known: {sorted(KNOWN_RULES)}."
        )
    rules = {**DEFAULTS, **declared}
    if rules["unicode"] is not False and rules["unicode"] not in UNICODE_FORMS:
        raise ValueError(
            f"standardise.unicode must be one of {sorted(UNICODE_FORMS)} or false, "
            f"got {rules['unicode']!r}."
        )
    if not isinstance(rules["null_if"], (list, tuple)):
        raise ValueError(f"standardise.null_if must be a list, got {rules['null_if']!r}.")
    rules["null_if"] = tuple(rules["null_if"])
    return rules


def standardise(value, rules: dict[str, Any] | None):
    """A value, canonicalised. Non-strings and None pass through: a
    number has no whitespace, and a real NULL is not a sentinel."""
    if rules is None or not isinstance(value, str):
        return value
    if rules["unicode"] is not False:
        value = unicodedata.normalize(rules["unicode"], value)
    if rules["collapse_whitespace"]:
        value = " ".join(value.split())
    elif rules["trim"]:
        value = value.strip()
    # AFTER the cleanups, so " N/A " counts as the sentinel it is, and
    # comparison is exact -- never case-insensitive, which would make
    # "null" the surname Null disappear.
    if value in rules["null_if"]:
        return None
    return value
