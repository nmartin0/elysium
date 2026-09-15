"""
Bronze: what the source said, before anything was done to it.

WHY IT EXISTS, and it is not performance. Until now the raw rows lived
only in memory -- read, cast, written, forgotten. So a value that
looked wrong had nothing to compare against except a source that may
since have changed, and adding an ontology field meant RE-READING THE
SILO rather than re-transforming what we already held.

Foundry's reason for ingesting "as-is from its most raw source, with no
external preprocessing" is exactly this: "every Ontology property value
traces back to a specific row in a specific raw file".

LINEAGE IS NOT INTEGRITY. Integrity asks whether a value is correct,
and this project already has machinery for that -- type coercion, drift
detection, optimistic concurrency, MAC and RBAC. Lineage asks where a
value CAME FROM. It does not make data right; it makes data
explicable.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

COLUMNS = ["id", "amount"]
TYPES = {"id": "string", "amount": "number"}


@pytest.fixture
def synced(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, amount TEXT)")
    connection.executemany(
        # "500.00" DELIBERATELY. Casting it to a number and back gives
        # "500.0" -- the trailing zero is lost, and that loss is
        # exactly what bronze exists to make visible. A value like
        # "500.0" would survive the round trip and prove nothing.
        "INSERT INTO t VALUES (?, ?)", [("1", "49.99"), ("2", "500.00")],
    )
    connection.commit()
    connection.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)
    return sync


def test_bronze_keeps_the_value_the_source_gave(synced):
    """THE WHOLE POINT, in one assertion.

    Silver holds 500.0 because the ontology declares `amount` a number.
    Bronze holds "500.0" because that is what the database said. The
    cast is now visible instead of lost -- which is the difference
    between "this value is wrong" and "this value was derived, and here
    is what it was derived from".
    """
    bronze = synced._catalog.load_table("bronze_s.t").scan().to_arrow().to_pydict()
    silver = synced._catalog.load_table("s.t").scan().to_arrow().to_pydict()

    assert bronze["amount"] == ["49.99", "500.00"]
    assert silver["amount"] == [49.99, 500.0]


def test_bronze_says_where_the_rows_came_from(synced):
    # "Where did this come from" answered in METADATA, not columns --
    # adding columns would make bronze a transformation of the data it
    # exists to preserve.
    properties = synced._catalog.load_table("bronze_s.t").properties

    assert properties["elysium.source_silo"] == "s"
    assert properties["elysium.source_table"] == "t"
    assert properties["elysium.layer"] == "bronze"


def test_bronze_says_when_they_were_read(synced):
    # "When was it read" comes free: Iceberg stamps every snapshot.
    snapshot = synced._catalog.load_table("bronze_s.t").current_snapshot()

    assert snapshot.timestamp_ms > 0


def test_bronze_is_not_the_silver_table(synced):
    # THE CONTROL. A bronze that was merely another name for silver
    # would pass a careless version of the first test.
    bronze = synced._catalog.load_table("bronze_s.t")
    silver = synced._catalog.load_table("s.t")

    assert bronze.name() != silver.name()
    assert bronze.scan().to_arrow().schema.field("amount").type != \
        silver.scan().to_arrow().schema.field("amount").type


def test_a_second_sync_updates_bronze_too(synced, tmp_path):
    # Bronze that went stale would be worse than none: it would look
    # like provenance while describing a read that no longer happened.
    connection = sqlite3.connect(tmp_path / "source.db")
    connection.execute("UPDATE t SET amount = '999.50' WHERE id = '1'")
    connection.commit()
    connection.close()

    synced.sync_table("s", "t", "id", COLUMNS, TYPES)

    bronze = synced._catalog.load_table("bronze_s.t").scan().to_arrow().to_pydict()
    assert "999.50" in bronze["amount"]


def test_a_bronze_failure_does_not_fail_the_sync(tmp_path, monkeypatch, caplog):
    """Losing bronze costs lineage; losing the sync costs the data.

    A deployment whose disk filled should serve stale-but-correct data
    rather than none -- and the warning has to say what was lost, or
    the lineage gap is itself invisible.
    """
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, amount TEXT)")
    connection.execute("INSERT INTO t VALUES ('1', '49.99')")
    connection.commit()
    connection.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})

    # Broken INSIDE _write_bronze, not instead of it. A first version
    # patched the method itself, which bypasses the try/except it is
    # testing -- so it asserted the error propagated and passed,
    # proving only that the monkeypatch worked.
    # BROKEN ONLY FOR BRONZE. A first version patched create_namespace
    # globally, which also broke the silver namespace created moments
    # later -- so the OSError that escaped came from the SILVER path
    # while bronze's own catch had worked correctly. The warning in the
    # log said so.
    original = type(sync._catalog).create_namespace

    def only_bronze_fails(self, namespace, *args, **kwargs):
        if str(namespace).startswith("bronze_"):
            raise OSError("disk full")
        return original(self, namespace, *args, **kwargs)

    monkeypatch.setattr(type(sync._catalog), "create_namespace", only_bronze_fails, raising=True)

    result = sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    # The sync succeeded and the mirror is correct...
    assert result.row_count == 1
    assert sync._catalog.load_table("s.t").scan().to_arrow().num_rows == 1
    # ...and the lost lineage is stated rather than silent.
    assert any("bronze" in record.message for record in caplog.records)

