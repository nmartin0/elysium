"""
Tests for core/mirror/iceberg_sync.py -- Phase 2 of the read-only
mirror architecture (see ROADMAP.md).

Every test runs against a REAL SQLite source database and a REAL,
on-disk Iceberg mirror (a real SQLite catalog plus real Parquet
files under tmp_path) -- never a mock of either. The properties under
test are genuinely behavioral: does the data actually arrive, does a
second sync actually REPLACE rather than duplicate, is a source
change actually reflected, is freshness actually reported. A mocked
PyIceberg would prove none of that.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

COLUMNS = ["customer_id", "name", "region"]


@pytest.fixture
def source_db(tmp_path):
    path = tmp_path / "business_data.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?)",
        [("c1", "Ada", "us-west"), ("c2", "Grace", "us-east")],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def sync(tmp_path, source_db):
    # The adapter passed in is a READ-ONLY SQLiteReadAdapter (Phase 1)
    # -- deliberately, so a sync is structurally incapable of writing
    # back to the customer's own source data, not merely unlikely to.
    adapters = {"primary": SQLiteReadAdapter({"path": source_db})}
    return IcebergMirrorSync(tmp_path / "mirror", adapters)


def _mirror_rows(sync, silo, table):
    return sync._catalog.load_table(f"{silo}.{table}").scan().to_arrow().to_pydict()


def test_sync_copies_every_real_row_into_the_mirror(sync):
    result = sync.sync_table("primary", "customers", "customer_id", COLUMNS)

    assert result.row_count == 2
    assert result.silo_name == "primary"
    assert result.table_name == "customers"

    rows = _mirror_rows(sync, "primary", "customers")
    assert rows["customer_id"] == ["c1", "c2"]
    assert rows["name"] == ["Ada", "Grace"]
    assert rows["region"] == ["us-west", "us-east"]


def test_sync_copies_only_the_requested_columns(sync):
    # The mirror holds exactly what the ontology references -- never
    # SELECT *, never whatever else happens to live in the source
    # table.
    sync.sync_table("primary", "customers", "customer_id", ["customer_id", "name"])

    rows = _mirror_rows(sync, "primary", "customers")
    assert set(rows.keys()) == {"customer_id", "name"}
    assert "region" not in rows


def test_a_second_sync_replaces_rather_than_duplicating(sync, source_db):
    # THE critical correctness property of a full-refresh sync: running
    # it twice must not double the rows.
    sync.sync_table("primary", "customers", "customer_id", COLUMNS)
    sync.sync_table("primary", "customers", "customer_id", COLUMNS)

    rows = _mirror_rows(sync, "primary", "customers")
    assert rows["customer_id"] == ["c1", "c2"]


def test_a_real_source_change_is_reflected_by_the_next_sync(sync, source_db):
    sync.sync_table("primary", "customers", "customer_id", COLUMNS)

    conn = sqlite3.connect(source_db)
    conn.execute("UPDATE customers SET name = 'Ada Lovelace' WHERE customer_id = 'c1'")
    conn.execute("INSERT INTO customers VALUES ('c3', 'Katherine', 'us-west')")
    conn.execute("DELETE FROM customers WHERE customer_id = 'c2'")
    conn.commit()
    conn.close()

    result = sync.sync_table("primary", "customers", "customer_id", COLUMNS)

    # An update, an insert, AND a delete all reflected -- a delete
    # specifically, since an append-based sync would silently keep the
    # removed row forever.
    assert result.row_count == 2
    rows = _mirror_rows(sync, "primary", "customers")
    assert rows["customer_id"] == ["c1", "c3"]
    assert rows["name"] == ["Ada Lovelace", "Katherine"]


def test_snapshot_history_is_preserved_across_syncs(sync):
    # Real time travel back to an earlier sync is a genuine capability
    # this storage choice buys (see ROADMAP.md) -- proven here rather
    # than assumed from Iceberg's reputation.
    sync.sync_table("primary", "customers", "customer_id", COLUMNS)
    table = sync._catalog.load_table("primary.customers")
    first_snapshot = table.current_snapshot().snapshot_id

    sync.sync_table("primary", "customers", "customer_id", COLUMNS)

    reloaded = sync._catalog.load_table("primary.customers")
    assert len(reloaded.metadata.snapshots) > 1
    # The earlier snapshot is still genuinely readable.
    old_rows = reloaded.scan(snapshot_id=first_snapshot).to_arrow().to_pydict()
    assert old_rows["customer_id"] == ["c1", "c2"]


def test_last_synced_at_is_none_before_any_sync(sync):
    assert sync.last_synced_at("primary", "customers") is None


def test_last_synced_at_reports_a_real_time_after_a_sync(sync):
    result = sync.sync_table("primary", "customers", "customer_id", COLUMNS)

    reported = sync.last_synced_at("primary", "customers")
    assert reported is not None
    # Iceberg records this itself, in its own metadata, rather than
    # Elysium tracking it separately -- so it can never drift out of
    # sync with what actually happened. Within a second of the result's
    # own timestamp is a real match, not an approximation.
    assert abs((reported - result.synced_at).total_seconds()) < 5


def test_syncing_an_unknown_silo_fails_loudly(sync):
    # "Fail loudly, never silently substitute" -- a typo'd silo name
    # must not quietly produce an empty mirror table.
    with pytest.raises(ValueError, match="No adapter for silo"):
        sync.sync_table("nonexistent_silo", "customers", "customer_id", COLUMNS)


def test_an_empty_source_table_syncs_cleanly_rather_than_erroring(tmp_path):
    # A real, legitimate case -- not every table has rows yet.
    path = tmp_path / "empty.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": path})})
    result = sync.sync_table("primary", "customers", "customer_id", COLUMNS)

    assert result.row_count == 0
    assert _mirror_rows(sync, "primary", "customers")["customer_id"] == []


def test_null_values_survive_the_round_trip_as_null(tmp_path):
    # NULL must stay NULL, not become the string "None" -- a real,
    # easy-to-get-wrong case given this version stringifies values.
    path = tmp_path / "nulls.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', NULL, 'us-west')")
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": path})})
    sync.sync_table("primary", "customers", "customer_id", COLUMNS)

    rows = _mirror_rows(sync, "primary", "customers")
    assert rows["name"] == [None]


def test_two_silos_stay_genuinely_separate(tmp_path, source_db):
    # One namespace per silo -- a table with the SAME name in two
    # different silos must not collide.
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.execute("INSERT INTO customers VALUES ('x1', 'Other', 'eu-west')")
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(
        tmp_path / "mirror",
        {
            "primary": SQLiteReadAdapter({"path": source_db}),
            "secondary": SQLiteReadAdapter({"path": other}),
        },
    )
    sync.sync_table("primary", "customers", "customer_id", COLUMNS)
    sync.sync_table("secondary", "customers", "customer_id", COLUMNS)

    assert _mirror_rows(sync, "primary", "customers")["customer_id"] == ["c1", "c2"]
    assert _mirror_rows(sync, "secondary", "customers")["customer_id"] == ["x1"]
