"""
Repairing a catalog that points at a metadata file which is not there.

WHAT GOES WRONG, established by reading pyiceberg rather than guessing:
commit_table calls _write_metadata BEFORE opening its database
session, so the ORDER is correct and matches the spec's guarantee that
a crash "costs orphan data files rather than a broken table".

THE GAP IS DURABILITY. The metadata is written through
`filesystem.open_output_stream(...)` and closed, with no fsync
anywhere in that path. A close() flushes to the operating system; it
does not force the data to disk. On a full disk or a power loss the
kernel can fail the writeback AFTER close() returned, so the catalog
commits a pointer to content that never landed.

This project's own development mirror hit exactly that when a
container filled its disk.

WHY A TOOL RATHER THAN "DELETE AND RE-SYNC": bronze and silver are
derivable and THE CHANGELOG IS NOT. A source holds "now" and cannot
say what a value used to be, so the obvious recovery destroys the one
thing that cannot be recovered.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from scripts.repair_catalog import find_broken

COLUMNS = ["id", "a"]
TYPES = {"id": "string", "a": "string"}


@pytest.fixture
def mirror(tmp_path):
    """A mirror with two commits, so there is something to fall back to."""
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
    connection.execute("INSERT INTO t VALUES ('1', 'x')")
    connection.commit()
    connection.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    connection = sqlite3.connect(source)
    connection.execute("UPDATE t SET a = 'CHANGED'")
    connection.commit()
    connection.close()
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    sync.mirror_path = tmp_path / "mirror"
    return sync


def _metadata_files(mirror):
    return sorted((mirror.mirror_path / "warehouse" / "s" / "t" / "metadata")
                  .glob("*.metadata.json"))


class TestDetection:
    def test_a_healthy_catalog_reports_nothing(self, mirror):
        # THE CONTROL. A tool that reported a healthy mirror as broken
        # would be switched off, and then nothing would be watching.
        assert find_broken(mirror.mirror_path / "catalog.db") == []

    def test_a_missing_metadata_file_is_found(self, mirror):
        _metadata_files(mirror)[-1].unlink()

        broken = find_broken(mirror.mirror_path / "catalog.db")

        assert [identifier for identifier, *_ in broken] == ["s.t"]

    def test_it_offers_the_newest_survivor(self, mirror):
        # Newest, not oldest: a repair should lose as little as
        # possible, and every earlier metadata file is a valid table.
        files = _metadata_files(mirror)
        files[-1].unlink()

        _, _, _, survivors = find_broken(mirror.mirror_path / "catalog.db")[0]

        assert survivors[-1] == files[-2]


class TestRepair:
    def test_repointing_makes_the_table_readable(self, mirror):
        """THE WHOLE POINT, and the reason re-syncing cannot do it.

        Every write begins by reading the current snapshot, and the
        current snapshot is the missing file -- so a repair attempt
        fails for the same reason the read does.
        """
        from pyiceberg.catalog.sql import SqlCatalog

        files = _metadata_files(mirror)
        files[-1].unlink()

        with pytest.raises(FileNotFoundError):
            mirror.catalog.load_table("s.t").scan().to_arrow()

        connection = sqlite3.connect(mirror.mirror_path / "catalog.db")
        connection.execute(
            "UPDATE iceberg_tables SET metadata_location = ? "
            "WHERE table_namespace = 's' AND table_name = 't'",
            (f"file://{files[-2]}",),
        )
        connection.commit()
        connection.close()

        fresh = SqlCatalog(
            "elysium_mirror",
            uri=f"sqlite:///{mirror.mirror_path / 'catalog.db'}",
            warehouse=f"file://{mirror.mirror_path / 'warehouse'}",
        )
        rows = fresh.load_table("s.t").scan().to_arrow().to_pydict()

        assert rows["id"] == ["1"]

    def test_a_table_with_no_survivors_is_not_offered_a_repair(self, mirror):
        # Said plainly rather than offered a repair that cannot work:
        # this is the case where the data is genuinely gone.
        for metadata_file in _metadata_files(mirror):
            metadata_file.unlink()

        _, _, _, survivors = find_broken(mirror.mirror_path / "catalog.db")[0]

        assert survivors == []


def test_object_storage_locations_are_skipped_rather_than_misreported(mirror):
    """An s3:// location cannot be checked with Path.exists().

    A tool reporting every S3 table as broken would be worse than one
    that declines, so those rows are skipped.
    """
    connection = sqlite3.connect(mirror.mirror_path / "catalog.db")
    connection.execute(
        "UPDATE iceberg_tables SET metadata_location = 's3://bucket/nope.json'")
    connection.commit()
    connection.close()

    assert find_broken(mirror.mirror_path / "catalog.db") == []
