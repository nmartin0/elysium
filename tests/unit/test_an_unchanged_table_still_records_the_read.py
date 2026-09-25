"""
A table that did not change still records that it was READ
(PA001-A5).

THE OVERLAY BOUND IS min() ACROSS EVERY TABLE -- deliberately, and the
reason is sound: a write applied after ANY table's last sync may not
be reflected yet, so taking the newest would drop the overlay for
tables that lag.

BUT THE TIMESTAMP ONLY ADVANCED WHEN THE DATA CHANGED. An unchanged
table wrote no snapshot and recorded nothing, so a LOOKUP TABLE THAT
NEVER CHANGES kept its first timestamp for ever -- and min() pinned
the bound to the day the mirror was built.

WHAT THAT COST, measured end to end:

    a write applied through Elysium sets tier = gold
    later, someone changes the same field DIRECTLY in the source to
    platinum
    a sync runs; source and mirror both say platinum
    the overlay still masks it with the older applied write
    -> the user is shown "gold"

THE OVERLAY EXISTS TO COVER THE GAP between a write and the next
sync. It is not meant to outlive the sync that closed it, and an
unrelated static table should not be able to keep it open
indefinitely.

A PROPERTY, NOT A SNAPSHOT. `set_properties` commits metadata without
adding to the table's history, so an unchanged table records the read
without inventing a version of data that did not change -- which is
what the no-new-snapshot behaviour was protecting, and it still holds.
"""

import sqlite3
import time

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.ontology.write_log import WriteLogWriter


@pytest.fixture
def mirror(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE lookup (id TEXT PRIMARY KEY, v TEXT)")
    conn.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, tier TEXT, region TEXT)")
    conn.execute("INSERT INTO lookup VALUES ('l1','static')")
    conn.execute("INSERT INTO customers VALUES ('c1','silver','us-west')")
    conn.commit()
    conn.close()
    write_log = WriteLogWriter(tmp_path / "wl.db")
    sync = IcebergMirrorSync(tmp_path / "mirror",
                              {"p": SQLiteReadAdapter({"path": source})},
                              write_log=write_log)

    def columns(table):
        return ["id", "v"] if table == "lookup" else ["id", "tier", "region"]

    def run():
        for table in ("lookup", "customers"):
            sync.sync_table("p", table, "id", columns(table), {})

    def sql(statement):
        conn = sqlite3.connect(source)
        conn.execute(statement)
        conn.commit()
        conn.close()

    def bound():
        return min(sync.last_synced_at("p", t) for t in ("lookup", "customers"))

    sync.run, sync.sql, sync.bound, sync.write_log_ = run, sql, bound, write_log
    return sync


class TestAnUnchangedTable:
    def test_its_read_time_advances(self, mirror):
        """THE REGRESSION TEST. `lookup` never changes, and used to
        keep its first timestamp for ever."""
        mirror.run()
        first = mirror.last_synced_at("p", "lookup")
        time.sleep(1.1)

        mirror.run()

        assert mirror.last_synced_at("p", "lookup") > first

    def test_no_new_snapshot_is_written(self, mirror):
        """The behaviour this must not cost. An unchanged table that
        wrote a snapshot every sync would grow history describing
        nothing, and every later publication would carry it."""
        mirror.run()
        before = len(mirror.catalog.load_table("p.lookup").snapshots())

        mirror.run()

        assert len(mirror.catalog.load_table("p.lookup").snapshots()) == before

    def test_the_rows_are_untouched(self, mirror):
        mirror.run()
        mirror.run()

        rows = mirror.catalog.load_table("p.lookup").scan().to_arrow().to_pylist()
        assert [r["v"] for r in rows] == ["static"]


class TestTheOverlayBound:
    def test_one_static_table_no_longer_pins_it(self, mirror):
        mirror.run()
        first = mirror.bound()
        time.sleep(1.1)

        mirror.run()

        assert mirror.bound() > first

    def test_a_stale_write_stops_masking_fresh_source_data(self, mirror):
        """THE HARM, end to end. An applied write, then the same field
        changed DIRECTLY in the source, then a sync. The user must see
        what the database says."""
        mirror.run()
        time.sleep(1.1)
        entry = mirror.write_log_.log_pending_update(
            "Customer", "c1", {"tier": "gold"}, {"tier": "silver"}, "u", "upgrade")
        mirror.write_log_.mark_applied(entry)
        mirror.sql("UPDATE customers SET tier='gold' WHERE id='c1'")
        time.sleep(1.1)
        mirror.sql("UPDATE customers SET tier='platinum' WHERE id='c1'")

        mirror.run()

        overlay = mirror.write_log_.get_applied_changes_since(
            "Customer", "c1", mirror.bound().isoformat())
        # None or {} -- the function says "nothing to overlay" both
        # ways, and the claim here is about the tier the user sees.
        assert not overlay, f"the overlay still masks the source with {overlay}"

    def test_a_write_made_AFTER_the_sync_is_still_overlaid(self, mirror):
        """The overlay's actual job, which this must not break: a
        write applied since the last sync is not in the mirror yet and
        must still be masked over reads."""
        mirror.run()
        time.sleep(1.1)
        entry = mirror.write_log_.log_pending_update(
            "Customer", "c1", {"tier": "gold"}, {"tier": "silver"}, "u", "upgrade")
        mirror.write_log_.mark_applied(entry)

        overlay = mirror.write_log_.get_applied_changes_since(
            "Customer", "c1", mirror.bound().isoformat())

        assert overlay == {"tier": "gold"}


class TestTheBoundIsTheOLDEST:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING. The tests above
    compute the bound themselves, so swapping min() for max() in the
    loader changed none of them.

    IT IS THE OLDEST ON PURPOSE: a write applied after ANY table's
    last sync may not be reflected in the mirror yet, so taking the
    NEWEST would silently drop the overlay for every table that lags
    behind -- and that is the same class of bug as A5, in the other
    direction."""

    def test_the_loader_takes_the_oldest_across_tables(self, mirror, tmp_path):
        from types import SimpleNamespace

        from core.deployment_loader import _mirror_last_synced_at

        mirror.run()
        time.sleep(1.1)
        mirror.sql("UPDATE customers SET tier='gold' WHERE id='c1'")
        mirror.run()

        schema = {
            "Lookup": {"id_field": "id", "security": {"field": "v"},
                        "storage": {"silo": "p", "table": "lookup",
                                     "id_column": "id"},
                        "fields": {"id": {"type": "data"}, "v": {"type": "data"}}},
            "Customer": {"id_field": "id", "security": {"field": "region"},
                          "storage": {"silo": "p", "table": "customers",
                                       "id_column": "id"},
                          "fields": {"id": {"type": "data"},
                                      "tier": {"type": "data"},
                                      "region": {"type": "data"}}},
        }
        config = SimpleNamespace(schema=schema, read_from_mirror=True,
                                  mirror_storage={})

        bound = _mirror_last_synced_at(config, tmp_path)

        oldest = min(mirror.last_synced_at("p", t).isoformat()
                     for t in ("lookup", "customers"))
        newest = max(mirror.last_synced_at("p", t).isoformat()
                     for t in ("lookup", "customers"))
        assert bound == oldest
        assert bound != newest, (
            "the two tables synced at the same instant; the test cannot "
            "distinguish oldest from newest")


class TestTheChangedPathIsUnchanged:
    def test_a_changed_table_still_advances_and_writes_a_snapshot(self, mirror):
        mirror.run()
        before = len(mirror.catalog.load_table("p.customers").snapshots())
        first = mirror.last_synced_at("p", "customers")
        time.sleep(1.1)
        mirror.sql("UPDATE customers SET tier='gold' WHERE id='c1'")

        mirror.run()

        assert len(mirror.catalog.load_table("p.customers").snapshots()) > before
        assert mirror.last_synced_at("p", "customers") > first
