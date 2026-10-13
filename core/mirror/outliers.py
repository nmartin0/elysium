"""Values that are unusual for their column, flagged and never acted on (R30).

    fields:
      amount:
        data_type: decimal
        outliers: true                    # Tukey's far-out fences, k = 3
      weight:
        outliers: {method: mad}           # robust z-score above 3.5
      postcode:
        outliers: {method: pattern}       # a shape almost no other value has

WARN ONLY, ALWAYS. An outlier is a value that is RARE, not one that is
wrong -- the largest order of the year is an outlier and the most
important row in the table. The pipeline's own rule is "do not adopt
automatic value repair" (a 2024 VLDB evaluation of twelve algorithms
found most introduce more errors than they remove), and quarantining a
row for being unusual is repair by another name. So a flag is counted,
recorded with the other warnings, and the row lands.

DECLARED PER FIELD, never inferred, like every rule here.

THE METHODS, each the textbook one rather than an invention:

  iqr      Tukey's fences: below Q1 - k*IQR or above Q3 + k*IQR. k = 3 is
           Tukey's "far out", chosen over his 1.5 ("outside") because a
           flag on 0.7% of normal data is noise, not news.
  mad      Iglewicz and Hoaglin's modified z-score, 0.6745 (x - median)
           / MAD, flagged above 3.5 -- their recommendation, robust to
           the outliers it is looking for, as a mean and standard
           deviation are not.
  pattern  each text value's SHAPE (digits to 9, letters to A, runs kept)
           compared with the column's: a shape held by under 1% of
           values, in a column where one shape holds at least 90%, is
           flagged. "SW1A 1AA" in a column of "SW1A 1AA"-shaped values
           passes; "unknown" does not.

TOO FEW VALUES, NO FLAGS: under MIN_VALUES there is no distribution to
be unusual against, and a flag would be a coin toss.
"""

import re
import statistics
from collections import Counter
from decimal import Decimal

METHODS = ("iqr", "mad", "pattern")
MIN_VALUES = 20
DEFAULT_K = 3.0
MAD_THRESHOLD = 3.5
#: pattern: a shape rarer than this share is unusual...
RARE_SHARE = 0.01
#: ...but only where one shape is this dominant -- a column of free text
#: has no usual shape, and every value would be flagged.
DOMINANT_SHARE = 0.90
_KEYS = frozenset({"method", "k"})


def outlier_settings(field_config) -> "dict | None":
    """A field's declaration, normalised; None when it declares none."""
    declared = field_config.get("outliers")
    if declared is None or declared is False:
        return None
    if declared is True:
        return {"method": "iqr", "k": DEFAULT_K}
    return {"method": declared.get("method", "iqr"), "k": declared.get("k", DEFAULT_K)}


def validate_outliers(object_types) -> None:
    """Refuses, at load, a declaration that could never work."""
    numeric = {"integer", "number", "decimal"}
    for type_name, type_def in object_types.items():
        for field_name, field in (type_def.get("fields") or {}).items():
            declared = field.get("outliers")
            if declared is None or declared is False or declared is True:
                if declared is True and (field.get("data_type") or "string") not in numeric:
                    raise ValueError(f"{type_name}.{field_name}: `outliers: true` measures "
                                     f"numbers; for text use {{method: pattern}}.")
                continue
            where = f"{type_name}.{field_name}.outliers"
            if not hasattr(declared, "get"):
                raise ValueError(f"{where} must be true or a mapping such as {{method: mad}}.")
            unknown = sorted(set(declared) - _KEYS)
            if unknown:
                raise ValueError(f"{where}: unknown key(s) {unknown}; known: {sorted(_KEYS)}.")
            method = declared.get("method", "iqr")
            if method not in METHODS:
                raise ValueError(f"{where}: method must be one of {list(METHODS)}, got {method!r}.")
            data_type = field.get("data_type") or "string"
            if method == "pattern" and data_type != "string":
                raise ValueError(f"{where}: pattern compares the shapes of text values.")
            if method != "pattern" and data_type not in numeric:
                raise ValueError(f"{where}: {method} measures numbers, and this is {data_type}.")
            k = declared.get("k", DEFAULT_K)
            if "k" in declared and (method != "iqr" or isinstance(k, bool)
                                    or not isinstance(k, (int, float)) or k <= 0):
                raise ValueError(f"{where}: k is a positive number, and applies to iqr only.")


def _shape(text: str) -> str:
    shape = re.sub(r"[0-9]+", "9", text)
    return re.sub(r"[^\W\d_]+", "A", shape)


def unusual(values: list, settings: dict) -> "dict[int, str]":
    """{index into `values`: why it is unusual}. Empty values are skipped."""
    present = [(index, value) for index, value in enumerate(values) if value is not None]
    if len(present) < MIN_VALUES:
        return {}
    if settings["method"] == "pattern":
        shapes = {index: _shape(str(value)) for index, value in present}
        counts = Counter(shapes.values())
        usual, held = counts.most_common(1)[0]
        if held < DOMINANT_SHARE * len(present):
            return {}
        return {index: (f"{values[index]!r} is shaped {shape!r}, which {counts[shape]} of "
                        f"{len(present)} values share; {held} are shaped {usual!r}")
                for index, shape in shapes.items()
                if counts[shape] < RARE_SHARE * len(present)}
    numbers = [(index, float(value) if not isinstance(value, Decimal) else float(value))
               for index, value in present]
    ordered = sorted(number for _, number in numbers)
    if settings["method"] == "mad":
        median = statistics.median(ordered)
        mad = statistics.median(abs(number - median) for number in ordered)
        if mad == 0:
            return {}
        return {index: (f"{values[index]!r} has a robust z-score of "
                        f"{0.6745 * (number - median) / mad:.1f} (median {median:g}); above "
                        f"{MAD_THRESHOLD} is unusual")
                for index, number in numbers
                if abs(0.6745 * (number - median) / mad) > MAD_THRESHOLD}
    q1, _, q3 = statistics.quantiles(ordered, n=4, method="inclusive")
    k = settings["k"]
    low, high = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
    return {index: (f"{values[index]!r} is outside {low:g} to {high:g}, Tukey's fences at "
                    f"k = {k:g} (Q1 {q1:g}, Q3 {q3:g})")
            for index, number in numbers if number < low or number > high}
