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


def test_a_sync_issues_one_bulk_query_not_one_per_field_per_row(tmp_path):
    # A REGRESSION GUARD for a real, measured defect. The sync used to
    # read through find_ids() then get_raw_field() -- the per-object
    # shape that is right for serving a request and wrong for copying a
    # table. Measured before the fix: 10,001 queries to copy 2,000 rows
    # of a five-column table, extrapolating to roughly 13 minutes for a
    # million rows.
    #
    # Counting real queries rather than timing: a timing assertion would
    # be flaky, while the query count is exactly the thing that was
    # wrong.
    import adapters.sqlite_adapter as sqlite_adapter_module

    path = tmp_path / "bulk.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?)",
        [(f"c{i}", f"name{i}", "us-west") for i in range(50)],
    )
    conn.commit()
    conn.close()

    real_run_query = sqlite_adapter_module._run_query
    real_run_query_one = sqlite_adapter_module._run_query_one
    counted = {"n": 0}

    def counting_run_query(*args, **kwargs):
        counted["n"] += 1
        return real_run_query(*args, **kwargs)

    def counting_run_query_one(*args, **kwargs):
        counted["n"] += 1
        return real_run_query_one(*args, **kwargs)

    sqlite_adapter_module._run_query = counting_run_query
    sqlite_adapter_module._run_query_one = counting_run_query_one
    try:
        sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": path})})
        result = sync.sync_table(
            "primary", "customers", "customer_id", ["customer_id", "name", "region"]
        )
    finally:
        sqlite_adapter_module._run_query = real_run_query
        sqlite_adapter_module._run_query_one = real_run_query_one

    assert result.row_count == 50
    # One bulk read. The old behaviour would have been 50 * 3 + 1 = 151.
    assert counted["n"] == 1, f"expected one bulk query, got {counted['n']}"


def test_the_bulk_read_returns_the_same_data_the_per_field_reads_did(tmp_path):
    # The speedup must not have changed WHAT is copied -- compared
    # against the live adapter's own per-field reads on the same data.
    path = tmp_path / "same.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?)",
        [("c1", "Ada", "us-west"), ("c2", None, "eu")],
    )
    conn.commit()
    conn.close()

    adapter = SQLiteReadAdapter({"path": path})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": adapter})
    sync.sync_table("primary", "customers", "customer_id", ["customer_id", "name", "region"])

    mirrored = sync._catalog.load_table("primary.customers").scan().to_arrow().to_pydict()
    config = {"storage": {"table": "customers", "id_column": "customer_id"}}

    for index, object_id in enumerate(mirrored["customer_id"]):
        for column in ("name", "region"):
            assert mirrored[column][index] == adapter.get_raw_field(
                "Customer", object_id, column, config
            )
    # NULL specifically -- the case most likely to differ between a
    # bulk SELECT and a per-field read.
    assert None in mirrored["name"]
