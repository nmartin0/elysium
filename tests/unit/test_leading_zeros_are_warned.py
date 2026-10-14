"""
An integer read with its leading zeros dropped is accepted, AND WARNED
(ZOO-14, decided by the owner 14 Oct).

"007" in a column declared `integer` becomes 7. Refusing it would break
working deployments, so it is still accepted -- but an id-like code
declared integer loses its padding, and nobody would notice. The sync
now counts them per column and reports them where the declared warn
rules go: SyncResult.warnings, recorded per table and shown in Admin.
"""

import sqlite3

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import LEADING_ZEROS_REASON, IcebergMirrorSync
from core.mirror.transform import transform_rows


def test_the_value_is_still_accepted_and_counted():
    result = transform_rows([{"code": "007"}, {"code": "-0042"}, {"code": "12"}, {"code": "0"}],
                            ["code"], {"code": "integer"})

    assert [row["code"] for row in result.rows] == [7, -42, 12, 0]
    assert result.leading_zeros == {"code": 2}


def test_only_integer_columns_are_counted():
    result = transform_rows([{"code": "007"}], ["code"], {"code": "string"})

    assert result.leading_zeros == {}


def test_a_real_sync_warns(tmp_path):
    source = tmp_path / "s.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, code TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)", [("a", "007"), ("b", "008"), ("c", "9")])
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})

    result = sync.sync_table("p", "t", "id", ["id", "code"], {"id": "string", "code": "integer"})

    (warning,) = [w for w in result.warnings if w.reason == LEADING_ZEROS_REASON]
    assert (warning.column, warning.rows) == ("code", 2)
