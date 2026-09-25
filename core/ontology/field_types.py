"""
field_types.py  (what data type a field's VALUES are -- the ontology's
own answer, not the source database's)

A real, deliberate addition, and a genuine gap this project shipped
without: `ontology_schema.yaml` declared only `type: data` or
`type: link` -- a STRUCTURAL distinction (is this a value, or a
reference to another object?), never a DATA-TYPE one. Nothing in the
ontology said whether a field holds text, a whole number, or a
decimal.

WHY THAT GAP MATTERED, concretely rather than theoretically: the
Phase 4 side-by-side verification measured `Account.balance` reading
as `900.0` (a float) from a live database but `'500.0'` (a string)
from the mirror, because core/mirror/iceberg_sync.py stores every
column as a string. Any caller doing arithmetic, comparison, or
formatting on that field behaves differently depending on a config
flag. The mirror needed real types, and the honest place for the
answer is the ontology itself -- the same place every other semantic
fact about a field already lives.

THE ALTERNATIVE THAT WAS REJECTED, and why: reading types from the
source database at sync time (SQLite's own PRAGMA table_info, and
each other engine's equivalent). Smaller, and it would have fixed the
immediate bug -- but it makes the mirror's own shape depend on the
source's, so a source schema change silently reshapes the mirror. It
also rests on something that isn't true: SQLite's declared column
types are advisory, not enforced, so a column declared TEXT can
genuinely hold an integer. The ontology is the semantic source of
truth in this project; "what type is this field" is a semantic
question.

DELIBERATELY SMALL SET, grounded in what the real fixture data
actually needs (verified directly against the real CREATE TABLE
statements: TEXT, INTEGER, and REAL columns) rather than invented to
be comprehensive. Adding a type later is easy; removing one that
turned out to be unused, or wrong, is a breaking schema change. Dates
are deliberately NOT a type here -- the fixture stores
transaction_date as TEXT, and a real date type raises genuine
questions (timezone handling, parse-failure behavior, format
declaration) that deserve their own design rather than being answered
in passing.

GENUINELY OPTIONAL, defaulting to "string". Every existing deployment's
own ontology_schema.yaml predates this field entirely and must stay
valid -- exactly the same "a deployment predating this feature is
still correct" discipline action_types and enabled_tools already
follow. A deployment that declares nothing gets the current behavior.

Used by: core/ontology/object_type_validation.py (validating what's
         declared), core/mirror/iceberg_sync.py (building a real,
         typed Arrow schema from it)
"""

import datetime
import decimal
import zoneinfo

import pyarrow as pa

# The declared name -> the real Arrow type the mirror stores it as.
# The ONE place this mapping exists.
# DECIMAL'S PRECISION AND SCALE, fixed rather than declared per field.
#
# 38 digits is decimal128's maximum and the widest any of our layers
# offers; 9 decimal places covers currency (2), currency with
# fractional cents (4), and unit prices that carry more. Choosing once
# means a deployment never has to answer "how many digits does this
# need" for every money column, and a value that does not fit fails
# loudly rather than rounding.
#
# PER-FIELD PRECISION IS THE ALTERNATIVE, and it is what PostgreSQL and
# Iceberg both allow. It is not obviously better: it makes every
# ontology longer, it makes changing a field's precision a schema
# migration, and it lets two fields holding the same currency disagree.
# Worth revisiting if a real deployment needs more than 38/9.
DECIMAL_PRECISION = 38
DECIMAL_SCALE = 9

FIELD_DATA_TYPES = {
    "string": pa.string(),
    "integer": pa.int64(),
    "number": pa.float64(),
    "boolean": pa.bool_(),
    # EXACT, WHERE `number` IS APPROXIMATE. `number` goes through
    # float(), which turns '1234.56789012345678901' into
    # 1234.567890123457 -- money silently becoming a different amount,
    # measured rather than feared.
    #
    # Separate from `number` rather than replacing it, which is what
    # every layer below us does: Foundry has Double and Decimal,
    # Iceberg has double and decimal(P,S), PostgreSQL has double
    # precision and numeric. They answer different questions. Floats
    # for measurement, decimals for money.
    "decimal": pa.decimal128(DECIMAL_PRECISION, DECIMAL_SCALE),
    # THREE TEMPORAL TYPES, MIRRORING ICEBERG, because the mirror IS
    # Iceberg and a type we invent has to be emulated -- which is where
    # guarantees quietly disappear.
    #
    # A DATE IS NOT AN INSTANT. A birthday, an invoice date, a contract
    # start have no time and no timezone. "Converting" one is the
    # classic bug where somebody's birthday moves a day for readers in
    # Auckland, so this type is never converted.
    "date": pa.date32(),
    # A WALL-CLOCK READING WITH NO ZONE, stored exactly as given. The
    # literature calls these "local observations of time recorded in an
    # unspecified time zone", and disambiguating them "a common data
    # cleaning problem". We do not guess: see `timezone` below.
    "timestamp": pa.timestamp("us"),
    # A TRUE INSTANT, stored UTC. Iceberg's spec: "values are stored as
    # UTC and do not retain a source time zone". PostgreSQL's reason
    # for timestamptz is the same -- it guarantees the precise moment
    # is stored in UTC, which "eliminates many time arithmetic
    # problems, and ensures portability".
    "timestamptz": pa.timestamp("us", tz="UTC"),
}

DEFAULT_FIELD_DATA_TYPE = "string"


def split_declared_type(declared: str) -> tuple[str, str | None]:
    """A declared type and its optional source zone.

    THE TWO TRAVEL TOGETHER, encoded as "timestamptz@America/New_York",
    because a `timestamptz` whose source is naive cannot be read
    without its zone -- the zone is part of what the type MEANS, not a
    setting beside it. One string cannot arrive without the other or be
    reunited with the wrong one.

    ONE PLACE THAT KNOWS THE ENCODING. A first version split it inline
    where the coercer needed it, and left `arrow_type_for` to receive
    the whole string and refuse it -- which broke the sync's schema
    builder rather than the coercion, several files away from the
    change. Both callers now come here.
    """
    data_type, _, zone = declared.partition("@")
    return data_type, zone or None


def arrow_type_for(data_type: str) -> pa.DataType:
    """The real Arrow type for a declared `data_type`. Raises on an
    unknown one rather than silently falling back to string -- a typo
    in a schema must fail loudly at load time, not quietly produce a
    mirror whose types are wrong."""
    if data_type not in FIELD_DATA_TYPES:
        raise ValueError(
            f"Unknown field data_type {data_type!r} -- "
            f"known types: {sorted(FIELD_DATA_TYPES)}"
        )
    return FIELD_DATA_TYPES[data_type]


def _parse_temporal(value, data_type: str):
    """A source value as a `date` or `datetime`, or a refusal.

    ALREADY-TYPED VALUES PASS STRAIGHT THROUGH. psycopg hands back
    `date` for a date column and `datetime` for a timestamp, so a live
    read needs no parsing. SQLite has no temporal types and returns
    strings for all three shapes, so a sync through bronze -- which
    stringifies -- always parses. Both paths must reach the same
    answer.

    ISO-8601 ONLY, and deliberately so. A format that has to be guessed
    is a format that will be guessed wrong: '01/05/2026' is the fifth
    of January in one country and the first of May in another, and
    nothing in the value says which. Accepting it would make the
    mirror's meaning depend on where it was built.
    """
    if isinstance(value, datetime.datetime | datetime.date):
        return value

    text = str(value).strip()
    try:
        # date FIRST, because fromisoformat on a datetime string raises
        # here and falls through -- where the reverse silently turns a
        # bare date into midnight.
        return datetime.date.fromisoformat(text)
    except ValueError:
        pass

    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        raise ValueError(
            f"{value!r} is not ISO-8601, so it cannot be read as a "
            f"{data_type}. A format that has to be guessed is a format "
            f"that will be guessed wrong."
        ) from None


# HOW SOURCES SPELL BOOLEANS (001's F-01). Lower-cased and stripped
# before the comparison, so 'TRUE' and ' t ' are the same word. A value
# outside these and outside the numbers still RAISES: the docstring
# below means it -- an honest mismatch is not silently defaulted.
_TRUE_WORDS = frozenset({"true", "t", "yes", "y", "on"})
_FALSE_WORDS = frozenset({"false", "f", "no", "n", "off"})


# The digits a declared number may be written with. `int("１２３")`
# returns 123 -- Python accepts every Unicode decimal digit -- and a
# mirror that quietly reads full-width digits as ASCII ones is
# INFERRING, which this file's whole contract forbids.
_ASCII_DIGITS = set("0123456789")


def _real_number(value):
    """A `number`, refusing the ones arithmetic cannot use (ZOO-19,
    ZOO-20, PR001-R26).

    float() ACCEPTS "NaN", "inf", "-inf" and "Infinity", and returns
    inf for "1e999" -- an overflow, silently, which is the worst of
    the set because it looks like a number that was simply large.

    NONE OF THESE SURVIVE A SUM. One NaN in a column poisons every
    total computed from it for ever: NaN + anything is NaN, and
    nothing reports it. An aggregate over a million good rows and one
    bad one returns NaN, and a person reads that as a system fault
    rather than as one cell somebody typed wrongly in 2019.

    REFUSED AS A ValueError, so it lands in the drift report that
    names the column and the value, exactly as any other unparseable
    cell does.
    """
    converted = float(value)
    if converted != converted:  # NaN is the only value unequal to itself
        raise ValueError(
            f"{value!r} is not a number a total could include. A `number` "
            f"column cannot hold NaN: one of them makes every sum over the "
            f"column NaN, silently."
        )
    if converted in (float("inf"), float("-inf")):
        raise ValueError(
            f"{value!r} is not a finite number. A `number` column cannot "
            f"hold an infinity -- and note that a value too large for a "
            f"float, such as 1e999, arrives here as one."
        )
    return converted


def _whole_number(value):
    """An `integer`, written in the digits everyone means (ZOO-13).

    `int("１２３")` is 123, because Python accepts every Unicode decimal
    digit. Reading full-width digits as ASCII ones is a GUESS about
    what the source meant, and a deployment that wants it can declare
    NFKC standardisation, which converts them before this point.

    WHAT IS DELIBERATELY STILL ACCEPTED: leading zeros. `int("007")`
    is 7, and that loses the padding of a code stored as text -- but
    the field was DECLARED an integer, and a zero-padded integer in a
    text source is ordinary and harmless. Refusing it would break
    working deployments to protect against a declaration mistake.
    Recorded as an owner decision (ZOO-14) rather than decided here.
    """
    if isinstance(value, str) and value.strip() and not (
            set(value.strip().lstrip("+-")) <= _ASCII_DIGITS):
        raise ValueError(
            f"{value!r} is not written in ASCII digits, so reading it as a "
            f"whole number would be a guess. Declare NFKC standardisation "
            f"on the field if the source really uses other digit forms."
        )
    return int(value)


def coerce(value, data_type: str, source_timezone: str | None = None):
    """A raw source value, converted to what its declared type says it
    is. None stays None -- a real NULL is not a type error.

    Deliberately raises on a genuine mismatch (e.g. a field declared
    `integer` whose source value is "abc") rather than silently
    substituting a default. That is a real, honest signal that the
    ontology and the source database disagree, which is exactly the
    kind of thing that should surface loudly during a sync rather than
    become a wrong value in the mirror.
    """
    if value is None:
        return None
    if data_type == "string":
        return str(value)
    if data_type == "integer":
        return _whole_number(value)
    if data_type == "number":
        return _real_number(value)
    if data_type == "decimal":
        # THROUGH str(), ALWAYS. Decimal(float) inherits the float's
        # error -- Decimal(0.1) is 0.1000000000000000055511151231... --
        # so a value that arrived as a float must be rendered as text
        # first. Bronze stores strings, so the normal path is already
        # text; this guards the case where it is not.
        try:
            converted = decimal.Decimal(str(value))
        except decimal.InvalidOperation as e:
            # AS A ValueError, BECAUSE THAT IS WHAT CALLERS CATCH
            # (PA001-C1). decimal.InvalidOperation derives from
            # ArithmeticError, NOT ValueError, so it sailed straight
            # through core/mirror/transform.py's `except (ValueError,
            # TypeError)` -- the handler that turns a bad value into a
            # named DriftedColumn. No column name, no example value, no
            # row count: run_sync recorded the whole table's refusal as
            # "[<class 'decimal.ConversionSyntax'>]".
            #
            # ONE "$5.00" IN 10,000 GOOD ROWS DOES THIS, and so do
            # "N/A", "1,234" and "TBD" -- the ordinary contents of a
            # money column somebody has been typing into by hand.
            raise ValueError(
                f"{value!r} is not a number, so it cannot be stored as a "
                f"`decimal`. Currency symbols, thousands separators and "
                f"placeholder text all look like this."
            ) from e
        if not converted.is_finite():
            # NaN AND INFINITY ARE NOT AMOUNTS. Decimal accepts both,
            # and either would reach the mirror as a value no
            # arithmetic can use. Found by mypy: as_tuple().exponent is
            # a letter rather than a number for these, so the precision
            # check below cannot even be applied to them.
            raise ValueError(
                f"{value!r} is not a finite number, so it cannot be stored "
                f"as a `decimal`."
            )
        # TOTAL DIGITS TOO, not just decimal places. Arrow refuses a
        # value that will not fit decimal128 -- verified -- but it
        # refuses at write time with "the string '1E+400' cannot be
        # represented", naming neither the column nor the row. Caught
        # here, the drift report says which field disagreed.
        # adjusted() RATHER THAN len(digits), which a first version used
        # and which is wrong for anything written in exponent form:
        # Decimal('1e400').as_tuple().digits is just (1,), because the
        # magnitude lives in the exponent. adjusted() gives the exponent
        # of the most significant digit, so the integer part occupies
        # adjusted() + 1 places.
        if converted.adjusted() + 1 > DECIMAL_PRECISION - DECIMAL_SCALE:
            raise ValueError(
                f"{value!r} is too large for this deployment's `decimal` "
                f"type, which holds "
                f"{DECIMAL_PRECISION - DECIMAL_SCALE} digits before the "
                f"decimal point."
            )
        exponent = converted.as_tuple().exponent
        if -int(exponent) > DECIMAL_SCALE:
            # REFUSED RATHER THAN ROUNDED. Rounding here would be the
            # silent loss this type exists to prevent, and a value too
            # precise to store is a real disagreement between the
            # ontology and the source.
            raise ValueError(
                f"{value!r} has more than {DECIMAL_SCALE} decimal places, "
                f"which this deployment's `decimal` type cannot store "
                f"without rounding."
            )
        return converted
    if data_type == "date":
        parsed = _parse_temporal(value, "date")
        if isinstance(parsed, datetime.datetime):
            # A TIME OF DAY IS NOT A DATE. fromisoformat happily turns
            # '2026-03-12' into midnight, so accepting a datetime here
            # would silently discard a real time -- and silently invent
            # one on the way back out.
            raise ValueError(
                f"{value!r} carries a time of day, so it is a timestamp "
                f"rather than a date. Declare the field `timestamp` or "
                f"`timestamptz`, or store only the date."
            )
        return parsed
    if data_type == "timestamp":
        parsed = _parse_temporal(value, "timestamp")
        if isinstance(parsed, datetime.datetime) and parsed.tzinfo is not None:
            # AN INSTANT IS NOT A WALL-CLOCK READING. Dropping the
            # offset here would turn a known moment into an unknown
            # one, which is a loss dressed up as a conversion.
            raise ValueError(
                f"{value!r} carries a UTC offset, so it names a real "
                f"instant rather than a local reading. Declare the field "
                f"`timestamptz`."
            )
        return parsed
    if data_type == "timestamptz":
        parsed = _parse_temporal(value, "timestamptz")
        if (
            isinstance(parsed, datetime.datetime)
            and parsed.tzinfo is None
            and source_timezone is not None
        ):
            # DECLARED, NEVER INFERRED. A field whose source zone is
            # known can say so, and a naive reading is then promoted to
            # the instant it always was. Someone had to write the zone
            # down, which is the difference between knowing and
            # assuming.
            try:
                parsed = parsed.replace(tzinfo=zoneinfo.ZoneInfo(source_timezone))
            except zoneinfo.ZoneInfoNotFoundError:
                raise ValueError(
                    f"{source_timezone!r} is not a known IANA timezone, so "
                    f"{value!r} cannot be promoted to an instant."
                ) from None
        if not isinstance(parsed, datetime.datetime) or parsed.tzinfo is None:
            # NOT PROMOTED BY GUESSING. Assuming UTC is a guess, and
            # assuming the server's zone is worse: it makes the same
            # data mean different things on two machines, which is the
            # coupling storing UTC exists to remove. A field whose
            # source zone is known declares it; see `timezone` in the
            # ontology.
            raise ValueError(
                f"{value!r} has no UTC offset, so it does not name an "
                f"instant. Declare the field `timestamp`, or give the "
                f"field a `timezone` so its source zone is stated rather "
                f"than guessed."
            )
        return parsed.astimezone(datetime.UTC)
    if data_type == "boolean":
        # SQLite has no real boolean -- it stores 0/1 -- so a plain
        # bool() on the string "0" would be WRONG (non-empty strings
        # are truthy). Going through int() first is what makes a
        # round-tripped "0" correctly become False.
        #
        # AND THE WORDS, which int() could not read (001's F-01). Every
        # other database writes booleans as text: Postgres gives
        # 't'/'f' and 'true'/'false', MySQL and CSV exports give
        # 'TRUE'/'FALSE' or 'yes'/'no'. Each raised here, and a raise
        # in coerce is reported by the sync as SCHEMA DRIFT -- so a
        # perfectly consistent boolean column could never sync, and
        # said the source had changed shape instead.
        if isinstance(value, str):
            spelled = value.strip().lower()
            if spelled in _TRUE_WORDS:
                return True
            if spelled in _FALSE_WORDS:
                return False
            try:
                return bool(int(spelled))
            except ValueError:
                raise ValueError(
                    f"{value!r} is not a boolean. Accepted: "
                    f"{', '.join(sorted(_TRUE_WORDS | _FALSE_WORDS))}, "
                    f"or a number, in any case."
                ) from None
        return bool(value)
    raise ValueError(f"Unknown field data_type {data_type!r}")
