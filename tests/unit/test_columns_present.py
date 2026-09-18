"""
An adapter can say which columns its source ACTUALLY has.

WHY IT EXISTS. The sync needs to know whether a column the ontology
declares has gone away. Until this method, a vanished column surfaced
as whatever the adapter's own read happened to raise -- storage
behaviour standing in for a policy, which is the thing core/mirror/ is
trying to stop doing (see HOT_RELOAD_PLAN.md step 5e).

It returns the TRUTH ON DISK, not the ontology's opinion of it. The
caller already knows what it declared; the whole value is the
difference between the two.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', 'Ada', 'us-west')")
    conn.commit()
    conn.close()
    return path


def test_reports_the_columns_a_table_has(source):
    adapter = SQLiteReadAdapter({"path": source})

    assert adapter.columns_present("customers") == {"customer_id", "name", "region"}


def test_reports_columns_of_an_EMPTY_table(source):
    # PRAGMA table_info, not a SELECT: a table can be emptied and
    # reshaped in the same migration, and a shape derived from rows
    # would report nothing at all for the emptied one.
    conn = sqlite3.connect(source)
    conn.execute("DELETE FROM customers")
    conn.commit()
    conn.close()
    adapter = SQLiteReadAdapter({"path": source})

    assert adapter.columns_present("customers") == {"customer_id", "name", "region"}


def test_a_dropped_column_stops_being_reported(source):
    # THE CASE THIS EXISTS FOR. The ontology still declares `region`;
    # the source no longer has it. That difference is what the drift
    # policy acts on.
    conn = sqlite3.connect(source)
    conn.execute("ALTER TABLE customers DROP COLUMN region")
    conn.commit()
    conn.close()
    adapter = SQLiteReadAdapter({"path": source})

    present = adapter.columns_present("customers")
    assert "region" not in present
    assert {"customer_id", "name"} <= present


def test_an_absent_table_is_an_empty_set_not_an_error(source):
    # Every declared column is then missing, which is ACCURATE -- a
    # dropped table is a dropped column for each of them -- and it lets
    # one code path describe both without the caller distinguishing a
    # failure from an answer.
    adapter = SQLiteReadAdapter({"path": source})

    assert adapter.columns_present("no_such_table") == set()


def test_an_unreadable_database_is_an_empty_set_too(tmp_path):
    # Same reasoning: nothing there satisfies a declared field, and a
    # caller asking "which columns exist" does not want to also handle
    # "the file is gone" separately.
    adapter = SQLiteReadAdapter({"path": tmp_path / "missing.db"})

    assert adapter.columns_present("customers") == set()


def test_the_mirror_reports_what_IT_holds(tmp_path):
    # The mirror answers a DIFFERENT question from the source, and
    # honestly: what was copied here, not what the source has now. The
    # sync asks the SOURCE adapter; asking the mirror is meaningful but
    # means something else.
    from adapters.sqlite_adapter import SQLiteReadAdapter as Source
    from core.mirror.iceberg_sync import IcebergMirrorSync
    from core.mirror.mirror_adapter import MirrorReadAdapter

    path = tmp_path / "src.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', 'Ada')")
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": Source({"path": path})})
    sync.sync_table("primary", "customers", "customer_id", ["customer_id", "name"],
                    {"customer_id": "string", "name": "string"})

    assert MirrorReadAdapter(sync._catalog, "primary").columns_present("customers") == {
        "customer_id", "name",
    }


def test_an_unmirrored_table_is_an_empty_set(tmp_path):
    from core.mirror.iceberg_sync import IcebergMirrorSync
    from core.mirror.mirror_adapter import MirrorReadAdapter

    sync = IcebergMirrorSync(tmp_path / "mirror", {})

    assert MirrorReadAdapter(sync._catalog, "primary").columns_present("nope") == set()
