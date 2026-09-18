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

import decimal

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
}

DEFAULT_FIELD_DATA_TYPE = "string"


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


def coerce(value, data_type: str):
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
        return int(value)
    if data_type == "number":
        return float(value)
    if data_type == "decimal":
        # THROUGH str(), ALWAYS. Decimal(float) inherits the float's
        # error -- Decimal(0.1) is 0.1000000000000000055511151231... --
        # so a value that arrived as a float must be rendered as text
        # first. Bronze stores strings, so the normal path is already
        # text; this guards the case where it is not.
        converted = decimal.Decimal(str(value))
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
    if data_type == "boolean":
        # SQLite has no real boolean -- it stores 0/1 -- so a plain
        # bool() on the string "0" would be WRONG (non-empty strings
        # are truthy). Going through int() first is what makes a
        # round-tripped "0" correctly become False.
        if isinstance(value, str):
            return bool(int(value))
        return bool(value)
    raise ValueError(f"Unknown field data_type {data_type!r}")
