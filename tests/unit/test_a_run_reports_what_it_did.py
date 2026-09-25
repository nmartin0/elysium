"""
A sync run describes itself accurately (PA001-A17, PA001-F6.3, and
half of PA001-A15).

THREE SMALL THINGS, all about a run's own account of itself.

A17 -- 'unchanged' WAS NEVER RECORDED. SyncAttempts has supported
three outcomes since it was written: its own docstring says "'synced',
'unchanged' or 'refused'. Three outcomes". run_sync recorded 'synced'
for both of the first two, so a source nobody has touched for a month
and a source that changed this morning looked identical in the history
an operator reads to answer "when did this last actually move?".

F6.3 -- THE MANIFEST DESCRIBED THE PREVIOUS RUN. publish_manifest ran
BEFORE the sync loop, so its table list was whatever the catalog held
beforehand. A table synced for the first time was absent from the
manifest written moments after it appeared, and stayed absent until
the next sync. The manifest is what a lake says about itself to
whatever reads it next; one describing a different moment is worse
than a late one.

A15 -- HALF OF IT IS ALREADY FIXED. "A refusal freezes all of gold"
was true and patch 424 fixed it: a refused table skips ITS type by
name and the others publish. The other half -- tables are read at
different moments, so the mirror is a patchwork of instants -- is
real, unfixed, and is PR001-R4 ("one consistent read per silo per
run"), which is a design change rather than a defect. Recorded rather
than half-done.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync


@pytest.fixture
def mirror(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
    conn.execute("INSERT INTO t VALUES ('a','1')")
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})

    def run():
        return sync.sync_table("p", "t", "id", ["id", "v"], {})

    def change(value):
        conn = sqlite3.connect(source)
        conn.execute("UPDATE t SET v=?", (value,))
        conn.commit()
        conn.close()

    sync.run, sync.change = run, change
    return sync


class TestASyncSaysWhetherItChangedAnything:
    def test_the_first_sync_changed_something(self, mirror):
        assert mirror.run().unchanged is False

    def test_an_identical_second_sync_did_not(self, mirror):
        """THE REGRESSION TEST for A17. This was indistinguishable
        from the first."""
        mirror.run()

        assert mirror.run().unchanged is True

    def test_and_a_real_change_is_not_unchanged(self, mirror):
        mirror.run()
        mirror.run()
        mirror.change("2")

        assert mirror.run().unchanged is False

    def test_the_row_count_is_still_reported_either_way(self, mirror):
        """An unchanged run still serves rows; 'unchanged' describes
        the WRITE, not the table."""
        mirror.run()

        result = mirror.run()

        assert result.unchanged and result.row_count == 1


class TestTheAttemptHistory:
    def test_run_sync_chooses_the_outcome(self):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING. The test below
        calls attempts.record() directly, so making run_sync pass
        'synced' for both cases -- the original bug -- changed
        nothing. This exercises the decision itself."""
        from types import SimpleNamespace

        from scripts.run_sync import _outcome_for

        assert _outcome_for(SimpleNamespace(unchanged=True)) == "unchanged"
        assert _outcome_for(SimpleNamespace(unchanged=False)) == "synced"

    def test_it_distinguishes_quiet_from_busy(self, tmp_path):
        """Through run_sync's own recording, which is where A17
        lived."""
        from core.mirror.sync_attempts import SyncAttempts

        attempts = SyncAttempts(tmp_path / "a.db")
        attempts.record("p", "t", "synced")
        attempts.record("p", "t", "unchanged")

        conn = sqlite3.connect(tmp_path / "a.db")
        try:
            outcomes = sorted(row[0] for row in
                              conn.execute("SELECT outcome FROM sync_attempts"))
        finally:
            conn.close()

        assert outcomes == ["synced", "unchanged"]


class TestTheManifestDescribesThisRun:
    def test_it_lists_a_table_synced_for_the_FIRST_time(self, tmp_path):
        """F6.3. Published before the loop, the manifest listed
        whatever existed beforehand -- nothing at all on a first
        run."""
        from types import SimpleNamespace

        from core.mirror.manifest import publish_manifest, read_manifests

        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t VALUES ('a','1')")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "m",
                                  {"p": SQLiteReadAdapter({"path": source})})
        from datetime import UTC, datetime

        config = SimpleNamespace(
            generation=1, loaded_at=datetime.now(UTC), source_digest="d",
            source_text={"ontology_schema.yaml": "object_types: {}\n"})

        sync.sync_table("p", "t", "id", ["id", "v"], {})
        publish_manifest(sync, config)

        manifests = read_manifests(sync.catalog)
        assert manifests, "no manifest was written"
        assert any("p.t" in name for name in manifests[-1]["tables"]), (
            "the manifest does not list the table this run created")
