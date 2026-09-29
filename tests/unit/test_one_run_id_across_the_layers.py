"""
One sync, one id, on every layer it writes (PR001-R9).

A sync writes bronze, silver, gold and an attempt record, and the only
thing connecting them was a timestamp -- so "what else happened in the
run that refused this table?" meant comparing clocks across four
layers and hoping no two runs overlapped. I answered that question by
timestamp three times in one week while investigating other findings.

A TABLE PROPERTY, NOT A COLUMN. It describes the WRITE, not the rows.
A column would change every row's hash on every run and make the
unchanged check meaningless -- the check that stops a quiet source
writing a snapshot a day.

NULLABLE EVERYWHERE, deliberately: a script or a test outside a run
has no id, and the property is not written rather than invented.

THESE TESTS ASSERT THE WIRING, not the behaviour, and that is the
point. This patch was built twice. The first time it was delivered and
never applied, and I did not check -- the same "reported versus
verified" gap I had been recording in other people's work all week.
Rebuilding it, the SAME call site failed to wire a SECOND time,
silently, because a multi-line string replacement did not match. On
both occasions every unit test passed and the id simply did not reach
gold. A real run found it; nothing else would have.
"""

import sqlite3
from pathlib import Path

from core.mirror.sync_attempts import SyncAttempts


class TestTheAttemptStore:
    def test_a_recorded_attempt_carries_the_run(self, tmp_path):
        SyncAttempts(tmp_path / "a.db").record("p", "t", "synced",
                                                run_id="run-abc")

        assert sqlite3.connect(tmp_path / "a.db").execute(
            "SELECT run_id FROM sync_attempts").fetchall() == [("run-abc",)]

    def test_an_attempt_without_one_is_allowed(self, tmp_path):
        SyncAttempts(tmp_path / "b.db").record("p", "t", "synced")

        assert sqlite3.connect(tmp_path / "b.db").execute(
            "SELECT run_id FROM sync_attempts").fetchall() == [(None,)]

    def test_a_store_that_predates_the_column_migrates(self, tmp_path):
        """`CREATE TABLE IF NOT EXISTS` does nothing to a table that is
        already there, so without a migration a deployment syncing for
        weeks would never gain the column -- and every insert naming it
        would fail."""
        conn = sqlite3.connect(tmp_path / "old.db")
        conn.execute(
            "CREATE TABLE sync_attempts (at REAL NOT NULL, silo TEXT NOT NULL, "
            "table_name TEXT NOT NULL, outcome TEXT NOT NULL, detail TEXT)")
        conn.execute("INSERT INTO sync_attempts VALUES (1.0,'p','t','synced',NULL)")
        conn.commit()
        conn.close()

        SyncAttempts(tmp_path / "old.db").record("p", "t", "synced",
                                                  run_id="run-xyz")

        assert sqlite3.connect(tmp_path / "old.db").execute(
            "SELECT run_id FROM sync_attempts ORDER BY at").fetchall() == [
                (None,), ("run-xyz",)]

    def test_a_refusal_carries_it_too(self, tmp_path):
        """The refusal is what somebody reads when something went
        wrong, so it is what most needs the id."""
        SyncAttempts(tmp_path / "c.db").record("p", "t", "refused", "why",
                                                run_id="run-abc")

        assert sqlite3.connect(tmp_path / "c.db").execute(
            "SELECT outcome, run_id FROM sync_attempts").fetchall() == [
                ("refused", "run-abc")]


class TestEveryLayerIsWired:
    """THE CALL SITE THAT FAILED TWICE gets its own assertion. Both
    times the failure was silent, both times every other test passed,
    and both times only a real sync showed it."""

    def test_the_sync_accepts_a_run_id(self):
        import inspect

        from core.mirror.iceberg_sync import IcebergMirrorSync

        assert "run_id" in inspect.signature(IcebergMirrorSync).parameters

    def test_gold_accepts_one(self):
        import inspect

        from core.mirror.gold import build_gold

        assert "run_id" in inspect.signature(build_gold).parameters

    def test_the_script_passes_it_to_the_gold_BUILDER(self):
        """`_build_gold(...)` -- the site that silently failed to wire
        on both attempts, leaving gold blank while bronze and silver
        carried the id."""
        source = Path("scripts/run_sync.py").read_text()
        start = source.index("failures += _build_gold")
        call = source[start:source.index(")", source.index("unsynced=unsynced", start))]

        assert "run_id=run_id" in call

    def test_and_the_builder_passes_it_to_build_gold(self):
        source = Path("scripts/run_sync.py").read_text()
        start = source.index("result = build_gold(")
        call = source[start:source.index("\n\n", start)]

        assert "run_id=run_id" in call

    def test_both_gold_publish_paths_record_it(self):
        """gold has two: a first build, and every later build through
        the audit branch."""
        source = Path("core/mirror/gold.py").read_text()

        assert source.count("_record_run(catalog, identifier, run_id)") == 2

    def test_bronze_and_silver_both_record_it(self):
        source = Path("core/mirror/iceberg_sync.py").read_text()

        assert "RUN_ID_PROPERTY" in source
        # two call sites plus the definition
        assert source.count("_read_properties(read_started_at") == 3

    def test_the_run_announces_itself(self):
        source = Path("scripts/run_sync.py").read_text()

        assert 'print(f"run {run_id}")' in source


class TestTheProperty:
    def test_it_is_absent_rather_than_empty_without_a_run(self):
        from core.mirror.iceberg_sync import _read_properties

        assert "elysium.run_id" not in _read_properties("2026-01-01", None)

    def test_and_present_with_one(self):
        from core.mirror.iceberg_sync import RUN_ID_PROPERTY, _read_properties

        assert _read_properties("2026-01-01", "abc")[RUN_ID_PROPERTY] == "abc"
