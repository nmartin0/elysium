"""
A source gaining a column must not freeze the mirror (PA001-F1).

THE WORST KIND OF FAILURE: everything reports success. One
ALTER TABLE ADD COLUMN at the source, and then, measured over three
syncs that each edited a row and inserted one:

    sync 2: reported OK, 2 rows | source has 3 rows | silver ['a', 'b']
    sync 3: reported OK, 2 rows | source has 4 rows | silver ['a', 'b']
    sync 4: reported OK, 2 rows | source has 5 rows | silver ['a', 'b']
    integrity: OK (no problems reported)

The table never recovers without someone noticing by hand, and nothing
tells them: check_mirror compares bronze and silver WITH EACH OTHER,
and they agreed -- both stale.

THREE FAULTS IN A ROW, each swallowed by an except that only warns:
bronze's overwrite raised because the Arrow table was wider than the
table; the changelog scanned the OLD snapshot for the NEW column list
and lost every change in that sync ("lost permanently", said the
warning, correctly); and sync_table then read bronze back
unconditionally, so silver was rebuilt from the PREVIOUS snapshot and
the fresh rows already in memory were discarded.

BRONZE NOW WIDENS, which is what silver has always done twenty lines
away, and the changelog reads only the columns the old snapshot has.

A COLUMN APPEARING IS ROUTINE. It is the source's schema, not ours,
and it must not stop the mirror tracking the columns the ontology DOES
declare.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.integrity import check_mirror


@pytest.fixture
def mirror(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT)")
    conn.executemany("INSERT INTO t VALUES (?,?)", [("1", "a"), ("2", "b")])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})

    def run():
        return sync.sync_table("p", "t", "id", ["id", "name"], {})

    def sql(*statements):
        conn = sqlite3.connect(source)
        for statement in statements:
            conn.execute(statement)
        conn.commit()
        conn.close()

    def names():
        rows = sync.catalog.load_table("p.t").scan().to_arrow().to_pylist()
        return sorted(r["name"] for r in rows)

    sync.run, sync.sql, sync.names = run, sql, names
    return sync


class TestTheFreeze:
    def test_the_mirror_keeps_tracking_the_source(self, mirror):
        """THE REGRESSION TEST FOR THE MEASURED FREEZE: three syncs,
        each adding a row, silver following every time."""
        mirror.run()
        mirror.sql("ALTER TABLE t ADD COLUMN notes TEXT")

        for i in range(3):
            mirror.sql(f"UPDATE t SET name='v{i}' WHERE id='1'",
                        f"INSERT INTO t VALUES ('n{i}','x',NULL)")
            result = mirror.run()

            assert result.row_count == 3 + i, f"frozen at sync {i + 2}"
            assert f"v{i}" in mirror.names()

    def test_bronze_widens_to_hold_the_new_column(self, mirror):
        """Bronze is the raw record. A column it cannot store is a
        column nothing can be traced back to."""
        mirror.run()
        mirror.sql("ALTER TABLE t ADD COLUMN notes TEXT",
                    "UPDATE t SET notes='hello' WHERE id='1'")
        mirror.run()

        columns = mirror.catalog.load_table("bronze_p.t").schema().column_names
        assert "notes" in columns
        rows = {r["id"]: r for r in
                mirror.catalog.load_table("bronze_p.t").scan().to_arrow().to_pylist()}
        assert rows["1"]["notes"] == "hello"

    def test_the_changelog_keeps_recording(self, mirror):
        """The warning said the change was "lost permanently", and it
        was -- including changes to columns that had existed all
        along."""
        mirror.run()
        mirror.sql("UPDATE t SET name='v1' WHERE id='1'")
        mirror.run()
        mirror.sql("ALTER TABLE t ADD COLUMN notes TEXT",
                    "UPDATE t SET name='v2' WHERE id='1'")
        mirror.run()

        recorded = [r["name"] for r in
                    mirror.catalog.load_table("changelog_p.t").scan().to_arrow().to_pylist()]
        assert "v2" in recorded

    def test_a_row_added_at_the_same_time_arrives(self, mirror):
        mirror.run()
        mirror.sql("ALTER TABLE t ADD COLUMN notes TEXT",
                    "INSERT INTO t VALUES ('3','c',NULL)")
        mirror.run()

        assert mirror.names() == ["a", "b", "c"]


class TestTheChangelogHalf:
    """PA001-A9, which F1 is incomplete without -- as the audit said
    and as the test above proved when bronze widened and the changelog
    still refused. The changelog's schema was fixed by the FIRST change
    set it ever recorded."""

    def test_a_change_to_a_NEW_column_is_recorded(self, mirror):
        mirror.run()
        mirror.sql("UPDATE t SET name='v1' WHERE id='1'")
        mirror.run()
        mirror.sql("ALTER TABLE t ADD COLUMN notes TEXT",
                    "UPDATE t SET notes='written' WHERE id='1'")
        mirror.run()

        rows = mirror.catalog.load_table("changelog_p.t").scan().to_arrow().to_pylist()
        assert "notes" in mirror.catalog.load_table("changelog_p.t").schema().column_names
        assert any(r.get("notes") == "written" for r in rows)

    def test_changes_to_OLD_columns_survive_the_same_sync(self, mirror):
        """The part that made this expensive: a new column did not just
        cost the new column's history, it cost EVERY change in that
        sync."""
        mirror.run()
        mirror.sql("UPDATE t SET name='v1' WHERE id='1'")
        mirror.run()
        mirror.sql("ALTER TABLE t ADD COLUMN notes TEXT",
                    "UPDATE t SET name='v2' WHERE id='1'",
                    "INSERT INTO t VALUES ('9','z',NULL)")
        mirror.run()

        rows = mirror.catalog.load_table("changelog_p.t").scan().to_arrow().to_pylist()
        assert {r["_change"] for r in rows if r["id"] == "9"} == {"INSERT"}
        assert "v2" in [r["name"] for r in rows]


class TestWhatMustNotChange:
    def test_a_DECLARED_column_vanishing_is_still_refused(self, mirror):
        """The fix widens for columns APPEARING. A declared column
        disappearing is drift and must still stop the table -- the
        check this could most easily have weakened."""
        mirror.run()
        mirror.sql("CREATE TABLE t2 AS SELECT id FROM t", "DROP TABLE t",
                    "ALTER TABLE t2 RENAME TO t")

        with pytest.raises(ValueError, match="gone"):
            mirror.run()

        assert mirror.names() == ["a", "b"], "silver lost its last good state"

    def test_an_undeclared_column_disappearing_does_not_freeze(self, tmp_path):
        """The other half the audit asked for. Bronze keeps the column
        with nulls -- pyiceberg accepts a narrower Arrow table for
        optional fields -- which is a stale column in the raw record,
        not a frozen table. Recorded rather than assumed."""
        source = tmp_path / "d.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, name TEXT, extra TEXT)")
        conn.execute("INSERT INTO t VALUES ('1','a','x')")
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "dm", {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table("p", "t", "id", ["id", "name"], {})

        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t2 AS SELECT id, name FROM t")
        conn.execute("DROP TABLE t")
        conn.execute("ALTER TABLE t2 RENAME TO t")
        conn.execute("UPDATE t SET name='changed' WHERE id='1'")
        conn.commit()
        conn.close()
        sync.sync_table("p", "t", "id", ["id", "name"], {})

        served = sync.catalog.load_table("p.t").scan().to_arrow().to_pylist()
        assert [r["name"] for r in served] == ["changed"]
        assert "extra" in sync.catalog.load_table("bronze_p.t").schema().column_names

    def test_an_unchanged_sync_is_still_a_no_op(self, mirror):
        """Widening must not make every sync write a snapshot."""
        mirror.run()
        before = len(mirror.catalog.load_table("bronze_p.t").snapshots())

        mirror.run()

        assert len(mirror.catalog.load_table("bronze_p.t").snapshots()) == before


class TestWhyNothingNoticed:
    def test_the_integrity_check_still_cannot_see_this_class_of_fault(self, mirror):
        """NOT A FIX, A RECORD. check_mirror compares bronze and silver
        WITH EACH OTHER, so when both were stale it reported no
        problems. It reports none now either, because the mirror is
        healthy -- but the blind spot is unchanged, and PA001-R8
        (reconciliation against the SOURCE) is the thing that would
        close it."""
        mirror.run()
        mirror.sql("ALTER TABLE t ADD COLUMN notes TEXT",
                    "INSERT INTO t VALUES ('3','c',NULL)")
        mirror.run()

        assert check_mirror(mirror.catalog).problems == []
