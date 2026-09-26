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

WHAT THIS DOES AND DOES NOT CLAIM. It gives each of those a form that
can be read back: JSON for structures, base64 for bytes, ISO-8601 for
durations. It is NOT the full declared-encoding design (PR001-R3),
which would let a deployment say how each column should be rendered
and guarantee a round trip. This is the narrower claim that no value
is reduced to a memory address or to syntax no parser accepts.

VALUES str() ALREADY RENDERS CANONICALLY are left alone -- Decimal,
date, datetime, UUID, int, bool. Changing their form would rewrite
every bronze table for no gain, and `str(Decimal("10.50"))` is exactly
what we want stored.
"""

import base64
import datetime
import json
from typing import Any


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
