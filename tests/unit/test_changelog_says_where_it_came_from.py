"""
Each changelog entry names the bronze snapshot it was compared with and
the run that noticed it (PA001-A13).

The audit's finding: before-images existed (R10), but nothing tied an
entry to the raw record it was derived from. Now `_compared_with` is the
bronze snapshot this read was diffed against and `_run_id` the sync run
-- together, both ends of the comparison. The NEW bronze snapshot cannot
be named: the changelog is written before bronze is overwritten, so that
a failed overwrite cannot lose the evidence.
"""

import sqlite3

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync


def test_an_entry_names_its_bronze_snapshot_and_its_run(tmp_path):
    source = tmp_path / "s.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
    connection.execute("INSERT INTO t VALUES ('1', 'x')")
    connection.commit()
    connection.close()
    first = IcebergMirrorSync(tmp_path / "m", {"s": SQLiteReadAdapter({"path": source})},
                               run_id="run-one")
    first.sync_table("s", "t", "id", ["id", "a"], {})
    before = first._catalog.load_table("bronze_s.t").current_snapshot().snapshot_id

    connection = sqlite3.connect(source)
    connection.execute("UPDATE t SET a = 'y' WHERE id = '1'")
    connection.commit()
    connection.close()
    second = IcebergMirrorSync(tmp_path / "m", {"s": SQLiteReadAdapter({"path": source})},
                                run_id="run-two")
    second.sync_table("s", "t", "id", ["id", "a"], {})

    entries = second._catalog.load_table("changelog_s.t").scan().to_arrow().to_pylist()
    assert entries, "the update was recorded"
    assert {entry["_compared_with"] for entry in entries} == {str(before)}
    assert {entry["_run_id"] for entry in entries} == {"run-two"}
