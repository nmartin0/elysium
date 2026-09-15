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



class TestRetention:
    """Bronze declares how long it keeps history, even though nothing
    can yet act on it.

    pyiceberg 0.12 HAS NO SNAPSHOT EXPIRY AT ALL -- checked, not
    assumed: no expire_snapshots, no ExpireSnapshots, and
    ManageSnapshots offers only branches, tags and rollback. So these
    properties reclaim nothing today.

    They are still worth declaring. They are the NAMES Iceberg defines
    for the policy, so the intent travels with the table rather than
    living in a runbook, and the day pyiceberg gains expiry -- or a
    Spark or DuckDB job runs over the same warehouse -- the policy is
    already there and already correct.

    "Bronze bloat" is the most commonly cited failure of this pattern,
    and bronze roughly doubles the growth rate because it stores every
    column rather than the declared ones.
    """

    def test_bronze_keeps_two_snapshots(self, synced):
        # TWO, because that is what a diff needs: current and previous.
        # A third buys nothing while costing a full copy -- Iceberg's
        # copy-on-write makes every retained snapshot a complete
        # rewrite.
        properties = synced._catalog.load_table("bronze_s.t").properties

        assert properties["history.expire.min-snapshots-to-keep"] == "2"

    def test_the_age_bound_exceeds_any_request_by_an_order_of_magnitude(self, synced):
        """THE RULE test_snapshot_retention_guard.py DEMANDS.

        A pinned generation's snapshot must not be reclaimed while a
        query is still reading it. A query is bounded by max_hops and
        the request timeout -- minutes at worst -- so a bound measured
        in days makes the hazard unreachable rather than unlikely.
        """
        from core.mirror.iceberg_sync import RETENTION_MARGIN_MS

        properties = synced._catalog.load_table("bronze_s.t").properties
        declared = int(properties["history.expire.max-snapshot-age-ms"])

        assert declared == RETENTION_MARGIN_MS
        assert declared >= 24 * 60 * 60 * 1000, "a bound under a day is not a margin"

    def test_the_minimum_wins_over_the_age_bound(self, synced):
        """Both rules, and their interaction.

        "Retention policies will never delete transactions that are in
        the latest view of any branch", with age selecting among the
        rest. min-snapshots-to-keep must therefore be >= 1, or a quiet
        week could leave a table with nothing to diff against.
        """
        properties = synced._catalog.load_table("bronze_s.t").properties

        assert int(properties["history.expire.min-snapshots-to-keep"]) >= 1

    def test_silver_does_not_inherit_the_bronze_policy(self, synced):
        # THE CONTROL. Silver's retention is a separate decision -- it
        # backs live reads through pinned generations, where bronze
        # backs a diff -- and applying one table's policy to the other
        # by accident is how a pinned snapshot gets reclaimed.
        properties = synced._catalog.load_table("s.t").properties

        assert "history.expire.min-snapshots-to-keep" not in properties
