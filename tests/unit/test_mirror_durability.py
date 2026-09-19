"""
The mirror's own files reach disk before the pointer is trusted.

NOT HYPOTHETICAL. This deployment hit the failure during development:
the disk filled mid-sync and the catalog afterwards named metadata
file 00008 when only 00007 existed on disk.
`scripts/repair_catalog.py` was written to recover from it.

THE ORDERING IS BACKWARDS BY DEFAULT. pyiceberg writes metadata
through an unsynced path -- verified, "fsync" appears nowhere in its
pyarrow IO or table modules -- while SQLite fsyncs its own commit. So
the POINTER is durable and the thing it points at is not, and a crash
strands a table rather than losing a commit. Losing the last sync is
recoverable by syncing again; a pointer into nothing is not.

TWO FSYNCS, NOT ONE. The file's CONTENTS and the directory ENTRY
naming it are separate writes.

MEASURED: eight fsyncs in one sync of a 200-row table, 293ms total.
Noise against a sync's normal duration.
"""

import os
from unittest.mock import patch

import pytest

from core.mirror.durability import (
    MirrorDurabilityError,
    force_table_metadata_to_disk,
    force_to_disk,
)


class TestItForcesBothTheFileAndItsName:
    def test_two_fsyncs_per_file(self, tmp_path):
        """THE FILE AND ITS DIRECTORY. Syncing only the file can leave
        it present with NO NAME after a crash, which reads as a missing
        file rather than a corrupt one."""
        target = tmp_path / "a.json"
        target.write_text("{}")
        calls = []

        with patch.object(os, "fsync", lambda fd: calls.append(fd)):
            force_to_disk(target)

        assert len(calls) == 2


class TestItRaisesRatherThanWarning:
    def test_a_failed_fsync_stops_the_caller(self, tmp_path):
        """A SYNC THAT CONTINUED would commit a pointer to data that
        may not survive a crash -- the exact failure this prevents."""
        target = tmp_path / "a.json"
        target.write_text("{}")

        def fails(fd):
            raise OSError(28, "No space left on device")

        with patch.object(os, "fsync", fails), pytest.raises(MirrorDurabilityError):
            force_to_disk(target)

    def test_it_does_not_retry(self, tmp_path):
        """ON LINUX A FAILED FSYNC MAY CLEAR THE ERROR STATE, so a
        second call can report success while the data is still lost --
        the fsyncgate behaviour that cost PostgreSQL a well-known
        post-mortem."""
        target = tmp_path / "a.json"
        target.write_text("{}")
        attempts = []

        def fails(fd):
            attempts.append(fd)
            raise OSError(5, "I/O error")

        with patch.object(os, "fsync", fails), pytest.raises(MirrorDurabilityError):
            force_to_disk(target)

        assert len(attempts) == 1

    def test_a_missing_file_is_an_error_not_a_shrug(self, tmp_path):
        with pytest.raises(MirrorDurabilityError):
            force_to_disk(tmp_path / "never-written.json")


class TestForcingAWholeTable:
    def test_it_reports_how_many_it_synced(self, tmp_path):
        """THE ONLY HONEST MEASURE of what this did: a caller cannot
        otherwise tell a table with no metadata from one where the
        scan silently matched nothing."""
        metadata = tmp_path / "ns" / "t" / "metadata"
        metadata.mkdir(parents=True)
        for i in range(3):
            (metadata / f"{i:05d}.metadata.json").write_text("{}")

        assert force_table_metadata_to_disk(tmp_path, "ns.t") == 3

    def test_a_table_never_written_is_not_an_error(self, tmp_path):
        # A table with no metadata directory has nothing to force, and
        # a sync that creates one forces it on the way through.
        assert force_table_metadata_to_disk(tmp_path, "ns.never") == 0

    def test_it_syncs_every_file_rather_than_guessing_the_newest(self, tmp_path):
        """IDENTIFYING "THE CURRENT ONE" means parsing the catalog's
        pointer, and a mistake there syncs the wrong file while
        reporting success. The files are small and few -- 49 across
        four tables on the shipped deployment."""
        metadata = tmp_path / "ns" / "t" / "metadata"
        metadata.mkdir(parents=True)
        for i in range(5):
            (metadata / f"{i:05d}.metadata.json").write_text("{}")

        assert force_table_metadata_to_disk(tmp_path, "ns.t") == 5


class TestTheSyncUsesIt:
    def test_a_real_sync_forces_its_metadata(self, tmp_path):
        """END TO END, because the module working says nothing about
        whether the sync calls it."""
        import sqlite3

        from adapters.sqlite_adapter import SQLiteReadAdapter
        from core.mirror.iceberg_sync import IcebergMirrorSync

        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
        conn.execute("INSERT INTO t VALUES ('1', 'x')")
        conn.commit()
        conn.close()

        sync = IcebergMirrorSync(
            tmp_path / "m", {"s": SQLiteReadAdapter({"path": source})},
        )
        calls = []
        real = os.fsync

        with patch.object(os, "fsync", lambda fd: calls.append(fd) or real(fd)):
            sync.sync_table(
                "s", "t", "id", ["id", "a"], {"id": "string", "a": "string"},
            )

        assert calls, "a sync committed without forcing its metadata to disk"
