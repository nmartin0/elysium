"""
Bronze's text decodes back to the values the source sent (R3).

Bronze stores strings, deliberately. R3 asked that the string be
RECOVERABLE: that a reader can turn bronze back into the source's values
without guessing. The sync now records, per column, the encoding its
values were written in, and `bronze_value` reverses each one. The
round trip for every encoding is a hypothesis property in
tests/unit/test_properties.py; this file checks it through a real sync.
"""

import json
import sqlite3

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.bronze_text import ENCODINGS_PROPERTY, MIXED, decoded_rows
from core.mirror.iceberg_sync import IcebergMirrorSync


def _source(path, rows):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, n INTEGER, x REAL, b BLOB, "
                       "s TEXT, loose)")
    connection.executemany("INSERT INTO t VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


ROWS = [("1", 7, 2.5, b"\x00\xffraw", "text", 5),
        ("2", None, -0.125, None, "more", "five")]


def _bronze(sync):
    table = sync._catalog.load_table("bronze_s.t")
    return table, table.scan().to_arrow().to_pylist()


def test_the_encodings_are_recorded_per_column(tmp_path):
    _source(tmp_path / "s.db", ROWS)
    sync = IcebergMirrorSync(tmp_path / "m", {"s": SQLiteReadAdapter({"path": tmp_path / "s.db"})})
    sync.sync_table("s", "t", "id", ["id", "n", "x", "b", "s", "loose"], {})

    table, _ = _bronze(sync)
    encodings = json.loads(table.properties[ENCODINGS_PROPERTY])
    assert encodings == {"id": "text", "n": "int", "x": "float", "b": "base64", "s": "text",
                         "loose": MIXED}


def test_bronze_decodes_to_what_the_source_sent(tmp_path):
    _source(tmp_path / "s.db", ROWS)
    sync = IcebergMirrorSync(tmp_path / "m", {"s": SQLiteReadAdapter({"path": tmp_path / "s.db"})})
    sync.sync_table("s", "t", "id", ["id", "n", "x", "b", "s", "loose"], {})

    table, rows = _bronze(sync)
    decoded = decoded_rows(rows, json.loads(table.properties[ENCODINGS_PROPERTY]))

    by_id = {row["id"]: row for row in decoded}
    assert by_id["1"] == {"id": "1", "n": 7, "x": 2.5, "b": b"\x00\xffraw", "s": "text",
                          "loose": "5"}  # MIXED: the text, never a guess
    assert by_id["2"]["n"] is None and by_id["2"]["x"] == -0.125


def test_a_changed_rows_read_keeps_what_bronze_already_knew(tmp_path):
    """R2 reads a few rows; the encodings of the rest are carried."""
    from core.mirror.incremental import IncrementalPolicy

    path = tmp_path / "i.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, b BLOB, v TEXT)")
    connection.executemany("INSERT INTO t VALUES (?, ?, ?)", [("1", b"\x01", "a"), ("2", None, "b")])
    connection.commit()
    connection.close()
    sync = IcebergMirrorSync(tmp_path / "im", {"s": SQLiteReadAdapter({"path": path})})
    sync.incremental = {("s", "t"): IncrementalPolicy(cursor="v")}
    sync.sync_table("s", "t", "id", ["id", "b", "v"], {})
    connection = sqlite3.connect(path)
    connection.execute("UPDATE t SET v = 'c' WHERE id = '2'")  # its b is still NULL
    connection.commit()
    connection.close()

    sync.sync_table("s", "t", "id", ["id", "b", "v"], {})

    table, _ = _bronze(sync)
    assert json.loads(table.properties[ENCODINGS_PROPERTY])["b"] == "base64"
