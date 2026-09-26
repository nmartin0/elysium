"""
Bronze records a value, not Python's description of it (PA001-S2).

BRONZE STORES STRINGS -- deliberately, so the raw record survives a
source whose column types change. The question is WHICH strings, and
it used `str(value)`, which is Python's DISPLAY form. For several
types a real database returns, that throws the value away:

    a JSON column   "{'a': True, 'b': None}"  not JSON: True, None
    an array        '[1, 2, 3]'               Python list syntax
    bytes           "b'\\x00\\x01binary'"       a repr, not the bytes
    a memoryview    '<memory at 0x7f...>'     A POINTER ADDRESS
    an interval     '2 days, 0:01:30'         English, not a format

THE MEMORYVIEW SETTLES IT. The value is gone entirely, replaced by an
address that differs on every run -- so two syncs of an UNCHANGED row
produce different bronze, and the changelog then records an edit that
never happened. That is not a fidelity question; it is fabricated
history.

THE SAME ENCODING IS USED FOR THE CHANGELOG, for exactly that reason:
it diffs these strings.

WHAT THIS DOES NOT CLAIM. It is not the declared-encoding design
(PR001-R3), which would let a deployment say how each column is
rendered and guarantee a round trip. It is the narrower claim that no
value is reduced to a memory address or to syntax no parser accepts.

VALUES str() ALREADY RENDERS CANONICALLY are untouched -- Decimal,
date, datetime, UUID, int, bool. Changing them would rewrite every
bronze table for no gain.
"""

import base64
import datetime
import decimal
import json
import sqlite3
import uuid

import pytest

from adapters.sqlalchemy_adapter import SQLAlchemyReadAdapter
from core.mirror.bronze_text import bronze_text
from core.mirror.iceberg_sync import IcebergMirrorSync


class TestValuesThatUsedToBeLost:
    def test_bytes_round_trip_through_base64(self):
        raw = b"\x00\x01binary"

        stored = bronze_text(raw)

        assert base64.b64decode(stored) == raw

    def test_a_memoryview_does_not_become_an_address(self):
        """THE ONE THAT MATTERS MOST. str(memoryview) is
        '<memory at 0x...>' -- a different string every run."""
        stored = bronze_text(memoryview(b"abc"))

        assert "memory at" not in stored
        assert base64.b64decode(stored) == b"abc"

    def test_the_same_bytes_render_identically_twice(self):
        """Because the changelog diffs these strings: a value whose
        text changes run to run records edits that never happened."""
        first = bronze_text(memoryview(b"abc"))
        second = bronze_text(memoryview(b"abc"))

        assert first == second

    def test_a_json_column_is_json(self):
        stored = bronze_text({"a": True, "b": None, "c": [1, 2]})

        assert json.loads(stored) == {"a": True, "b": None, "c": [1, 2]}

    def test_a_dict_renders_identically_whatever_its_order(self):
        """Python dicts keep insertion order, so two rows with the
        same content could otherwise differ as text."""
        assert bronze_text({"a": 1, "b": 2}) == bronze_text({"b": 2, "a": 1})

    def test_an_array_is_json(self):
        assert json.loads(bronze_text([1, 2, 3])) == [1, 2, 3]

    def test_a_set_is_sorted_first(self):
        """A set has no order. Without sorting, two syncs of the same
        row can disagree."""
        assert bronze_text({"b", "a"}) == bronze_text({"a", "b"})

    @pytest.mark.parametrize("delta,expected", [
        (datetime.timedelta(days=2, seconds=90), "PT172890S"),
        (datetime.timedelta(seconds=1.5), "PT1.5S"),
        (datetime.timedelta(seconds=-30), "-PT30S"),
        (datetime.timedelta(0), "PT0S"),
    ])
    def test_an_interval_is_iso_8601(self, delta, expected):
        assert bronze_text(delta) == expected


class TestValuesThatWereAlreadyRight:
    """Untouched on purpose: changing them would rewrite every bronze
    table in every deployment for no gain."""

    @pytest.mark.parametrize("value,expected", [
        (decimal.Decimal("10.50"), "10.50"),
        (datetime.date(2026, 5, 1), "2026-05-01"),
        (datetime.datetime(2026, 5, 1, 9, 30), "2026-05-01 09:30:00"),
        (uuid.UUID("12345678-1234-5678-1234-567812345678"),
         "12345678-1234-5678-1234-567812345678"),
        (42, "42"), (True, "True"), ("already text", "already text"),
    ])
    def test_it_is_unchanged(self, value, expected):
        assert bronze_text(value) == expected

    def test_None_stays_None(self):
        """Bronze distinguishes a missing value from an empty one, and
        always has."""
        assert bronze_text(None) is None


class TestThroughARealDatabase:
    def test_a_blob_column_survives_the_sync(self, tmp_path):
        """End to end, through the SQLAlchemy adapter that returns the
        awkward types in the first place."""
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, payload BLOB)")
        conn.execute("INSERT INTO t VALUES ('a', ?)", (b"\x00\x01binary",))
        conn.commit()
        conn.close()
        adapter = SQLAlchemyReadAdapter({"url": f"sqlite:///{source}"})
        sync = IcebergMirrorSync(tmp_path / "m", {"p": adapter})

        sync.sync_table("p", "t", "id", ["id", "payload"], {})

        stored = sync.catalog.load_table("bronze_p.t") \
            .scan().to_arrow().to_pylist()[0]["payload"]
        assert base64.b64decode(stored) == b"\x00\x01binary"

    def test_an_unchanged_blob_row_writes_no_new_snapshot(self, tmp_path):
        """The consequence of the address problem, measured: bronze
        that differs run to run makes every sync look like a change."""
        source = tmp_path / "s2.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, payload BLOB)")
        conn.execute("INSERT INTO t VALUES ('a', ?)", (b"\x00\x01binary",))
        conn.commit()
        conn.close()
        adapter = SQLAlchemyReadAdapter({"url": f"sqlite:///{source}"})
        sync = IcebergMirrorSync(tmp_path / "m2", {"p": adapter})
        sync.sync_table("p", "t", "id", ["id", "payload"], {})
        before = len(sync.catalog.load_table("bronze_p.t").snapshots())

        sync.sync_table("p", "t", "id", ["id", "payload"], {})

        assert len(sync.catalog.load_table("bronze_p.t").snapshots()) == before
