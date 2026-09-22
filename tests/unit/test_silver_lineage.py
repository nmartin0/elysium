"""
Where a silver row came from (GOLD-1's last stage,
MEDALLION_PIPELINE.md's S6).

WHY GOLD NEEDS IT: when two sources disagree about one entity's field,
survivorship must say which source won, and a person must be able to
check. A value with no provenance cannot be argued with.

THE SPLIT IS BY STABILITY, and it is not cosmetic: the sync skips
writing a new snapshot when the source is unchanged -- measured at
27.2 MB down to 0.9 -- by comparing the rows it would write against
those already there. A per-row timestamp would change every run and
defeat that skip forever, so run-level facts are table PROPERTIES.
"""

import sqlite3
import time
from datetime import date
from decimal import Decimal

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.lineage import (
    BRONZE_SNAPSHOT_PROPERTY,
    LINEAGE_COLUMNS,
    row_hash,
    with_lineage,
)

ARGS = ("p", "t", "id", ["id", "name"], {"id": "string", "name": "string"})


class TestTheRowHash:
    def test_the_same_values_hash_the_same(self):
        assert row_hash({"a": 1, "b": "x"}, ["a", "b"]) == row_hash({"b": "x", "a": 1}, ["a", "b"])

    def test_a_changed_value_changes_it(self):
        assert row_hash({"a": 1}, ["a"]) != row_hash({"a": 2}, ["a"])

    def test_a_type_change_changes_it(self):
        """A source that changed a column's type changed the row."""
        assert row_hash({"a": 1}, ["a"]) != row_hash({"a": "1"}, ["a"])

    def test_even_when_the_two_spell_the_same(self):
        """WHERE THE TYPE IN THE MATERIAL EARNS ITS PLACE: a date and its
        text both encode as '2026-01-01', so without the type they would
        hash alike -- and a column that turned from a date into text
        would look unchanged."""
        assert row_hash({"a": date(2026, 1, 1)}, ["a"]) != row_hash({"a": "2026-01-01"}, ["a"])

    def test_and_a_decimal_is_not_its_text(self):
        assert row_hash({"a": Decimal("49.99")}, ["a"]) != row_hash({"a": "49.99"}, ["a"])

    def test_null_is_not_the_empty_string(self):
        assert row_hash({"a": None}, ["a"]) != row_hash({"a": ""}, ["a"])

    def test_columns_not_declared_are_not_hashed(self):
        assert row_hash({"a": 1, "extra": "x"}, ["a"]) == row_hash({"a": 1}, ["a"])

    @pytest.mark.parametrize("value", [date(2026, 1, 1), Decimal("49.99")])
    def test_values_json_cannot_hold_still_hash(self, value):
        assert isinstance(row_hash({"a": value}, ["a"]), str)


class TestWhatEachRowCarries:
    def test_the_source_it_came_from(self):
        rows = with_lineage([{"id": "a"}], ["id"], "primary_sql", "customers")

        assert rows[0]["_silo"] == "primary_sql"
        assert rows[0]["_source_table"] == "customers"

    def test_and_nothing_else_is_disturbed(self):
        rows = with_lineage([{"id": "a", "name": "Ada"}], ["id", "name"], "p", "t")

        assert rows[0]["id"] == "a" and rows[0]["name"] == "Ada"


@pytest.fixture
def synced(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO t VALUES (?,?)", [("a", "Ada"), ("b", "Bram")])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})
    sync.sync_table(*ARGS)
    return sync, source


def _rows(sync):
    return {row["id"]: row for row in sync._catalog.load_table("p.t").scan().to_arrow().to_pylist()}


class TestThroughTheSync:
    def test_every_row_carries_its_lineage(self, synced):
        sync, _ = synced

        row = _rows(sync)["a"]

        assert all(column in row for column in LINEAGE_COLUMNS)
        assert (row["_silo"], row["_source_table"]) == ("p", "t")

    def test_the_bronze_snapshot_is_recorded_on_the_table(self, synced):
        """A fact about the RUN, so a property -- and what lets any row
        trace back to what the source said."""
        sync, _ = synced
        table = sync._catalog.load_table("p.t")

        recorded = table.properties[BRONZE_SNAPSHOT_PROPERTY]

        bronze = sync._catalog.load_table("bronze_p.t").current_snapshot().snapshot_id
        assert recorded == str(bronze)

    def test_an_unchanged_source_still_writes_no_new_snapshot(self, synced):
        """THE MEASUREMENT THIS DESIGN PROTECTS: 27.2 MB down to 0.9."""
        sync, _ = synced
        before = sync._catalog.load_table("p.t").current_snapshot().snapshot_id
        time.sleep(1.1)

        sync.sync_table(*ARGS)

        assert sync._catalog.load_table("p.t").current_snapshot().snapshot_id == before

    def test_a_changed_row_changes_only_its_own_hash(self, synced):
        sync, source = synced
        before = {key: row["_row_hash"] for key, row in _rows(sync).items()}
        conn = sqlite3.connect(source)
        conn.execute("UPDATE t SET name = 'Ada L' WHERE id = 'a'")
        conn.commit()
        conn.close()

        sync.sync_table(*ARGS)

        after = {key: row["_row_hash"] for key, row in _rows(sync).items()}
        assert after["a"] != before["a"]
        assert after["b"] == before["b"]

    def test_a_table_synced_before_lineage_existed_gains_the_columns(self, tmp_path):
        """union_by_name evolves the schema: an existing mirror is not
        rebuilt by hand."""
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO t VALUES ('a', 'Ada')")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})
        # A table written the way the sync did before this stage.
        import pyarrow as pa
        sync._ensure_namespace("p")
        table = sync._catalog.create_table(
            "p.t", schema=pa.schema([("id", pa.string()), ("name", pa.string())]))
        table.append(pa.table({"id": ["a"], "name": ["Ada"]}))

        sync.sync_table(*ARGS)

        assert all(column in _rows(sync)["a"] for column in LINEAGE_COLUMNS)
