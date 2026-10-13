"""Numbers and dates as a source's people write them (DEP-1, ZOO-12/17/18/21).

THE PROBLEM. A source maintained by hand in Brazil writes `1.234,56`
and `02/01/2024`; one in the United States writes `1,234.56` and
`1/2/2024`. The same characters mean different values -- `1.234` is
one-point-two in one and twelve hundred in the other, and `02/01` is
the second of January or the first of February -- and nothing in the
value says which. That is why field_types.py refuses everything but
machine formats: "a format that has to be guessed is a format that will
be guessed wrong".

THE ANSWER IS TO STOP GUESSING BY BEING TOLD. A deployment declares the
locale its sources are written in (`source_locale:` in config.yaml),
and a silo whose people write differently overrides it (`locale:` in
data_silos.yaml). Every value is then read by that locale's rules and
no other. Nothing is inferred from the data.

WHERE THE RULES COME FROM: the Unicode CLDR, through Babel -- the
standard the operating systems and browsers themselves use. Measured
from it on 2026-10-12, for the owner's question "US or South American":

    locale   decimal  group  short date     so 1.234,5 / 02/01/2024 is
    en_US    .        ,      M/d/yy         (refused) / 1 February
    pt_BR    ,        .      dd/MM/y        1234.5 / 2 January
    es_AR    ,        .      d/M/yy         1234.5 / 2 January
    es_CL    ,        .      dd-MM-yy       1234.5 / 2 January
    es_CO    ,        .      d/MM/yy        1234.5 / 2 January
    es_PE    .        ,      d/MM/yy        (refused) / 2 January
    es_VE, es_UY, es_PY, es_BO, es_EC: as es_AR

SO "SOUTH AMERICAN" IS NOT ONE FORMAT, which is why this takes a locale
rather than a choice of two: Peru writes numbers as the US does and
dates as Brazil does, and Chile separates dates with dashes. (Mexico,
often grouped with them, is Peru's shape too.) Naming the country gets
each right; naming a continent would get Peru's numbers wrong.

WHAT IS STILL REFUSED, deliberately:

  TWO-DIGIT YEARS. `1/2/24` -- CLDR's own short pattern for en_US --
  needs a century, and choosing one is a guess. A source exporting
  them must export four digits; the row is quarantined and says so.

  MALFORMED GROUPING. Babel is used in STRICT mode, so `1.5` under
  pt_BR is refused rather than read as fifteen, and `1234.5` under
  pt_BR -- a machine-format number in a source declared Brazilian --
  is refused rather than read as twelve thousand three hundred and
  forty-five. Strict grouping is what separates a value written by the
  locale's rules from one that merely contains its characters.

  CURRENCY SYMBOLS AND ACCOUNTING NEGATIVES. `R$ 1.234,56` and
  `(1,234)` are formatting, not numbers, and stripping them is a
  separate declaration nobody has made.

WHAT IS ALWAYS ACCEPTED, in every locale: ISO-8601 dates
(`2024-01-02`), which cannot be misread, so a source mixing them with
local dates loses nothing.

PERCENTAGES are fractions: `5%` is 0.05, as a spreadsheet stores it.
Only into a `number` or `decimal`; an `integer` cannot hold 0.05.

APPLIED ONLY TO TEXT. A value the source DATABASE typed -- a number
column, a date column -- is already unambiguous and is never re-read
through a locale. core/mirror/iceberg_sync.py decides which columns
arrived as text before bronze turned every value into a string.
"""

import datetime
import re
from decimal import Decimal, InvalidOperation

from babel import Locale, UnknownLocaleError
from babel.dates import get_date_format
from babel.numbers import NumberFormatError, parse_decimal

#: Written in config.yaml or data_silos.yaml to say "machine formats
#: only" -- for a silo that must not inherit the deployment's locale.
NO_LOCALE = "none"

NUMERIC_TYPES = frozenset({"integer", "number", "decimal"})
TEMPORAL_TYPES = frozenset({"date", "timestamp", "timestamptz"})

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].*)?$")
_TIME = re.compile(
    r"^(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?\s*(?P<ampm>[AaPp]\.?\s?[Mm]\.?)?$")


def normalise_locale(declared, where: str) -> "str | None":
    """A declared locale as Babel names it (`pt_BR`), None for `none`.

    REFUSED AT LOAD when CLDR does not know it: a misspelt `pt-BRR`
    silently ignored would leave every value in that silo quarantined
    with nothing pointing at the cause.
    """
    if declared is None:
        return None
    if not isinstance(declared, str) or not declared.strip():
        raise ValueError(f"{where} must be a locale such as en_US or pt_BR, got {declared!r}.")
    text = declared.strip()
    if text.lower() == NO_LOCALE:
        return None
    try:
        return str(Locale.parse(text.replace("-", "_")))
    except (UnknownLocaleError, ValueError):
        raise ValueError(
            f"{where}: {declared!r} is not a locale CLDR knows. Use a language and "
            f"country, such as en_US, pt_BR, es_AR or es_CL, or `none` for machine "
            f"formats only."
        ) from None


def _date_order(locale: str) -> str:
    """'MDY', 'DMY' or 'YMD', from the locale's own short date pattern."""
    pattern = get_date_format("short", locale=locale).pattern
    positions = {}
    for letter in "dMy":
        index = pattern.find(letter)
        if index >= 0:
            positions[letter] = index
    order = sorted(positions, key=positions.__getitem__)
    return "".join({"d": "D", "M": "M", "y": "Y"}[letter] for letter in order)


def localised_number(text: str, locale: str) -> Decimal:
    """`text` read by `locale`'s decimal and grouping rules, strictly."""
    stripped = text.strip()
    try:
        return parse_decimal(stripped, locale=locale, strict=True)
    except (NumberFormatError, InvalidOperation):
        raise ValueError(
            f"{text!r} is not a number as {locale} writes one. "
            f"(This silo is declared {locale}; a number written another way is "
            f"refused rather than guessed at.)"
        ) from None


def _localised_date(text: str, locale: str) -> datetime.date:
    parts = re.split(r"[/.\-]", text)
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"{text!r} is not a date as {locale} writes one.")
    by_letter = dict(zip(_date_order(locale), parts, strict=True))
    if len(by_letter["Y"]) != 4:
        raise ValueError(
            f"{text!r} has a two-digit year, and choosing its century would be a "
            f"guess. Export four-digit years from this source.")
    try:
        return datetime.date(int(by_letter["Y"]), int(by_letter["M"]), int(by_letter["D"]))
    except ValueError:
        raise ValueError(f"{text!r} is not a real date as {locale} writes one.") from None


def _localised_time(text: str) -> datetime.time:
    match = _TIME.match(text.strip())
    if not match:
        raise ValueError(f"{text!r} is not a time of day.")
    hour, minute = int(match["h"]), int(match["m"])
    second = int(match["s"] or 0)
    if match["ampm"]:
        meridiem = match["ampm"].lower().replace(".", "").replace(" ", "")
        if not 1 <= hour <= 12:
            raise ValueError(f"{text!r}: a 12-hour clock has no hour {hour}.")
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    return datetime.time(hour, minute, second)


def to_canonical(value: str, data_type: str, locale: str) -> str:
    """The machine form of a locale-written value, for coerce() to read.

    Returns text in the form field_types.coerce already accepts -- a
    plain decimal, an ISO date -- so every check coerce makes (finite,
    in range, whole, the declared timezone) still applies afterwards.
    """
    text = value.strip()
    if not text:
        return value
    if data_type in NUMERIC_TYPES:
        if text.endswith("%"):
            if data_type == "integer":
                raise ValueError(f"{value!r} is a percentage; an integer cannot hold it.")
            return str(localised_number(text[:-1], locale) / 100)
        return str(localised_number(text, locale))
    if data_type in TEMPORAL_TYPES:
        if _ISO_DATE.match(text):
            return text
        date_part, _, time_part = text.partition(" ")
        day = _localised_date(date_part, locale)
        if data_type == "date":
            if time_part:
                raise ValueError(f"{value!r} carries a time; the field is a date.")
            return day.isoformat()
        moment = datetime.datetime.combine(
            day, _localised_time(time_part) if time_part else datetime.time())
        return moment.isoformat()
    return value
