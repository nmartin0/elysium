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

import pyarrow as pa

# The declared name -> the real Arrow type the mirror stores it as.
# The ONE place this mapping exists.
FIELD_DATA_TYPES = {
    "string": pa.string(),
    "integer": pa.int64(),
    "number": pa.float64(),
    "boolean": pa.bool_(),
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
    if data_type == "boolean":
        # SQLite has no real boolean -- it stores 0/1 -- so a plain
        # bool() on the string "0" would be WRONG (non-empty strings
        # are truthy). Going through int() first is what makes a
        # round-tripped "0" correctly become False.
        if isinstance(value, str):
            return bool(int(value))
        return bool(value)
    raise ValueError(f"Unknown field data_type {data_type!r}")
