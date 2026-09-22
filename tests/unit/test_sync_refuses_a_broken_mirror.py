"""
A sync refuses when the catalog and the warehouse disagree (roadmap
item 8), instead of dying inside pyiceberg after doing the work.

WHAT GOES WRONG: Iceberg commits by writing a metadata file and then
swapping the catalog's pointer, and pyiceberg does not fsync the file.
A full disk or a power cut leaves the pointer naming content that never
landed -- which happened to this project's own development mirror, the
catalog naming metadata file 00008 when only 00007 existed.

MEASURED BEFORE: the second sync raised a bare FileNotFoundError from
inside pyiceberg, naming a path and nothing else, AFTER reading the
source.
"""

import sqlite3
from pathlib import Path

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.integrity import unreadable_tables

ARGS = ("primary", "customers", "customer_id", ["customer_id", "name"],
        {"customer_id": "string", "name": "string"})


@pytest.fixture
def mirrored(tmp_path):
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', 'Ada')")
    conn.commit()
    conn.close()
    adapter = SQLiteReadAdapter({"path": source})
    adapter.reads = 0
    real = adapter.read_all_rows

    def counted(*args, **kwargs):
        adapter.reads += 1
        return real(*args, **kwargs)
    adapter.read_all_rows = counted
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": adapter})
    sync.sync_table(*ARGS)
    return sync, adapter


def _break_the_catalogs_word(sync, identifier="primary.customers"):
    """Delete the metadata file the catalog names -- the disk-full shape."""
    location = sync._catalog.load_table(identifier).metadata_location
    Path(location.replace("file://", "")).unlink()


class TestTheRefusal:
    def test_the_sync_refuses(self, mirrored):
        sync, _ = mirrored
        _break_the_catalogs_word(sync)

        with pytest.raises(ValueError, match="catalog and the warehouse disagree"):
            sync.sync_table(*ARGS)

    def test_it_names_the_table_and_how_to_repair_it(self, mirrored):
        sync, _ = mirrored
        _break_the_catalogs_word(sync)

        with pytest.raises(ValueError) as refused:
            sync.sync_table(*ARGS)

        assert "primary.customers" in str(refused.value)
        assert "scripts.repair_catalog" in str(refused.value)

    def test_it_reads_the_source_no_times(self, mirrored):
        """BEFORE ANYTHING ELSE: the old failure came after the read."""
        sync, adapter = mirrored
        _break_the_catalogs_word(sync)
        before = adapter.reads

        with pytest.raises(ValueError):
            sync.sync_table(*ARGS)

        assert adapter.reads == before

    def test_a_broken_BRONZE_table_is_caught_too(self, mirrored):
        sync, _ = mirrored
        _break_the_catalogs_word(sync, "bronze_primary.customers")

        with pytest.raises(ValueError, match="bronze_primary.customers"):
            sync.sync_table(*ARGS)


class TestWhatIsNotADisagreement:
    def test_a_healthy_mirror_syncs(self, mirrored):
        sync, _ = mirrored

        assert sync.sync_table(*ARGS).row_count == 1

    def test_a_table_not_synced_yet_is_fine(self, mirrored):
        """The first sync of a table finds nothing, which is normal."""
        sync, _ = mirrored

        assert unreadable_tables(sync._catalog, ("primary.never_synced",)) == {}

    def test_a_namespace_that_does_not_exist_is_fine(self, mirrored):
        sync, _ = mirrored

        assert unreadable_tables(sync._catalog, ("no_such_silo.t",)) == {}
