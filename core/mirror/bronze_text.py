"""Turning a source value into the text bronze stores (PA001-S2).

BRONZE STORES STRINGS. That is its contract and it is deliberate: the
raw record has to survive a source whose column types change, and text
is the one form that always can.

THE QUESTION IS WHICH TEXT. Bronze used `str(value)`, which is
Python's *display* form, and for several types SQLAlchemy returns that
throws the value away:

    a JSON column   {'a': True, 'b': None}  -- not JSON: `True`, `None`
    an array        '[1, 2, 3]'             -- Python list syntax
    bytes           "b'\\x00\\x01binary'"     -- a repr, not the bytes
    a memoryview    '<memory at 0x7f...>'   -- A POINTER ADDRESS
    an interval     '2 days, 0:01:30'       -- no parser accepts this

The memoryview is the one that settles it. The value is gone entirely,
replaced by an address that differs on every run, so two syncs of an
unchanged row produce different bronze -- and the changelog then
records a change that did not happen.

WHAT THIS DOES: each of those gets a form that can be read back --
JSON for structures, base64 for bytes, ISO-8601 for durations -- AND
(R3, 13 October) the round trip is guaranteed rather than hoped for.
`bronze_encoding` names the encoding a value was written in; the sync
records it per column on the bronze table (ENCODINGS_PROPERTY); and
`bronze_value` reverses it. tests/unit/test_properties.py checks the
round trip with hypothesis for every encoding.

WHY RECORDED AND NOT DECLARED. The R3 design had the deployment declare
each column's rendering. What a declaration was FOR is the round trip,
and the sync already sees every value's type, so it can say what it
did instead of being told -- no configuration to get wrong, and no
column the declaration forgot. A column whose values arrived as more
than one type is recorded as MIXED, and decodes as the text it is:
that is the honest answer, since "5" and 5 render identically.

VALUES str() ALREADY RENDERS CANONICALLY are left alone -- Decimal,
date, datetime, UUID, int, bool. Changing their form would rewrite
every bronze table for no gain, and `str(Decimal("10.50"))` is exactly
what we want stored.
"""

import base64
import datetime
import decimal
import json
import re
import uuid
from typing import Any

#: The bronze table property holding {column: encoding}, as JSON (R3).
ENCODINGS_PROPERTY = "elysium.bronze.encodings"
#: A column whose values arrived as more than one type.
MIXED = "mixed"


def bronze_text(value: Any) -> "str | None":
    """One value, as the text bronze records.

    None stays None: bronze distinguishes a missing value from an
    empty one, and always has.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        # BASE64, NOT repr. A memoryview's str() is its ADDRESS, and
        # bytes' str() is a Python literal that no other reader parses.
        # Base64 is the one encoding every language has and that
        # survives a text column unchanged.
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, datetime.timedelta):
        # ISO-8601 duration. `str(timedelta)` gives "2 days, 0:01:30",
        # which is English rather than a format.
        total = value.total_seconds()
        seconds = f"{abs(total):.6f}".rstrip("0").rstrip(".")
        return f"{'-' if total < 0 else ''}PT{seconds}S"
    if isinstance(value, (dict, list, tuple)):
        # JSON, so it is readable by something other than Python.
        # sort_keys so an unchanged row renders identically twice --
        # the changelog diffs these strings, and a dict that iterated
        # in a different order would look like an edit.
        return json.dumps(value, sort_keys=True, default=str)
    if isinstance(value, (set, frozenset)):
        # A SET HAS NO ORDER, so it is sorted before rendering. Without
        # that, two syncs of the same row can disagree.
        return json.dumps(sorted(value, key=str), default=str)
    return str(value)


# -- the round trip (R3) ----------------------------------------------------

_BY_TYPE = (
    (bool, "bool"),          # before int: bool IS an int
    (str, "text"),
    ((bytes, bytearray, memoryview), "base64"),
    (datetime.timedelta, "iso8601-duration"),
    ((dict, list, tuple), "json"),
    ((set, frozenset), "json-set"),
    (decimal.Decimal, "decimal"),
    (datetime.datetime, "datetime"),  # before date: a datetime IS a date
    (datetime.date, "date"),
    (datetime.time, "time"),
    (int, "int"),
    (float, "float"),
    (uuid.UUID, "uuid"),
)


def bronze_encoding(value: Any) -> "str | None":
    """The encoding bronze_text writes this value in; None for None. A
    type nothing here knows is "text": str() was its encoding, and its
    text is all a reader can be promised."""
    if value is None:
        return None
    for kinds, name in _BY_TYPE:
        if isinstance(value, kinds):
            return name
    return "text"


def encoding_of_type(kind: type) -> str:
    """bronze_encoding for a TYPE -- what the sync tracks per column, a
    set of types being far cheaper to keep than a check per value."""
    for kinds, name in _BY_TYPE:
        if issubclass(kind, kinds):
            return name
    return "text"


def column_encoding(types: "set[type]") -> "str | None":
    """One column's encoding from the types its values arrived as."""
    names = {encoding_of_type(kind) for kind in types if kind is not type(None)}
    if not names:
        return None
    return next(iter(names)) if len(names) == 1 else MIXED


_DURATION = re.compile(r"^(-?)PT([0-9]+(?:\.[0-9]+)?)S$")


def bronze_value(text: "str | None", encoding: "str | None") -> Any:
    """The value bronze_text was given, from the text it wrote and the
    encoding recorded for its column. An unknown or MIXED encoding
    returns the text: never a guess."""
    if text is None:
        return None
    if encoding == "bool":
        return text == "True"
    if encoding == "base64":
        return base64.b64decode(text)
    if encoding == "iso8601-duration":
        match = _DURATION.match(text)
        if match is None:
            return text
        seconds = decimal.Decimal(match.group(2))
        whole, fraction = divmod(seconds, 1)
        value = datetime.timedelta(seconds=int(whole),
                                   microseconds=int((fraction * 1_000_000).to_integral_value()))
        return -value if match.group(1) else value
    if encoding == "json":
        return json.loads(text)
    if encoding == "json-set":
        return set(json.loads(text))
    if encoding == "decimal":
        return decimal.Decimal(text)
    if encoding == "datetime":
        return datetime.datetime.fromisoformat(text)
    if encoding == "date":
        return datetime.date.fromisoformat(text)
    if encoding == "time":
        return datetime.time.fromisoformat(text)
    if encoding == "int":
        return int(text)
    if encoding == "float":
        return float(text)
    if encoding == "uuid":
        return uuid.UUID(text)
    return text


def decoded_rows(rows: "list[dict]", encodings: "dict[str, str | None]") -> "list[dict]":
    """Bronze rows as the values the source sent, through the encodings
    recorded on the bronze table (ENCODINGS_PROPERTY)."""
    return [{column: bronze_value(text, encodings.get(column)) for column, text in row.items()}
            for row in rows]
