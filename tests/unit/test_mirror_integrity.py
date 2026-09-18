"""
Is the mirror self-consistent on its own terms?

A NARROW QUESTION DELIBERATELY. Not "is the data correct" --
correctness is a property of the SOURCE and the mirror cannot know it.
Self-consistency is a property of the mirror, and the mirror is the
only thing that can check it.

WHY IT MATTERS MORE THAN IT USED TO. Until the changelog existed,
everything in the mirror was derivable: if it was wrong, delete it and
re-sync. The changelog is not derivable -- a source holds "now" and
cannot say what a value used to be -- so from that point the mirror
holds something only it holds, and "is it intact" became a question
with consequences.

EVERY TEST HERE DAMAGES A REAL MIRROR rather than building a fake
catalog, because a check that only recognises damage it was handed is
a check of the test's imagination.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.integrity import check_mirror

COLUMNS = ["id", "a"]
TYPES = {"id": "string", "a": "string"}

SCHEMA = {
    "Thing": {
        "id_field": "id",
        "storage": {"table": "t", "id_column": "id"},
        "fields": {
            "id": {"type": "data", "data_type": "string"},
            "a": {"type": "data", "data_type": "string"},
        },
    },
}


@pytest.fixture
def mirror(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
    connection.executemany("INSERT INTO t VALUES (?, ?)", [("1", "x"), ("2", "y")])
    connection.commit()
    connection.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)
    sync.mirror_path = tmp_path / "mirror"
    return sync


def test_a_healthy_mirror_reports_nothing(mirror):
    """THE CONTROL, and the one that keeps the rest honest.

    A check that reported problems on a correct mirror would be
    switched off within a week, and then nothing would be checking.
    """
    report = check_mirror(mirror._catalog, SCHEMA, mirror.mirror_path / "warehouse")

    assert report.ok, report.problems
    assert report.tables_checked == 2


def test_silver_without_bronze_is_reported(mirror):
    # Bronze tolerates its own failures so the sync can continue, so
    # this is exactly the state that tolerance produces -- and without
    # bronze, silver's rows cannot be traced to what the source said.
    mirror._catalog.drop_table("bronze_s.t")

    report = check_mirror(mirror._catalog)

    assert not report.ok
    assert any("no bronze table" in problem for problem in report.problems)


def test_a_row_count_mismatch_is_reported(mirror):
    """Only the TYPES differ between the layers, never the rows.

    So a count mismatch means a transform dropped rows and said
    nothing, which no other check would catch.
    """
    import pyarrow as pa

    bronze = mirror._catalog.load_table("bronze_s.t")
    bronze.overwrite(pa.table({"id": ["1"], "a": ["x"]}))

    report = check_mirror(mirror._catalog)

    # THE WORDING NOW NAMES THE DIRECTION. This test shrinks BRONZE,
    # leaving silver serving more than was last fetched -- which is
    # not a dropped row, it is a silver older than the bronze beside
    # it. The old message called both cases "dropped rows silently".
    assert any("older than bronze" in problem for problem in report.problems)


def test_a_declared_column_missing_from_silver_is_reported(mirror):
    """A MISSING COLUMN IS INVISIBLE WITHOUT THIS.

    The UI renders a blank cell, which reads as "this object has no
    value" rather than "this column was never synced" -- and those are
    very different things to tell someone.
    """
    schema = {
        "Thing": {
            **SCHEMA["Thing"],
            "fields": {**SCHEMA["Thing"]["fields"], "never_synced": {"type": "data"}},
        },
    }

    report = check_mirror(mirror._catalog, schema)

    assert any("never_synced" in problem for problem in report.problems)


def test_a_link_field_without_a_column_is_not_a_fault(mirror):
    # A link declared on the far side has no column of its own, so its
    # absence is correct rather than missing.
    schema = {
        "Thing": {
            **SCHEMA["Thing"],
            "fields": {**SCHEMA["Thing"]["fields"],
                       "others": {"type": "link", "target": "Other"}},
        },
    }

    report = check_mirror(mirror._catalog, schema)

    assert report.ok, report.problems


def test_data_on_disk_the_catalog_forgot_is_reported(mirror):
    """THE CHECK THAT MATTERS MOST FOR A TEARDOWN.

    Our catalog is a SQLite file beside the warehouse. Lose it and the
    lake is a directory of Parquet nobody can interpret -- so a table
    the catalog has stopped listing is the visible edge of that
    failure, while it is still recoverable.
    """
    mirror._catalog.drop_table("s.t")

    report = check_mirror(mirror._catalog, warehouse_dir=mirror.mirror_path / "warehouse")

    assert any("catalog does not list it" in problem for problem in report.problems)


def test_it_runs_without_an_ontology_at_all(mirror):
    """THE CASE THIS EXISTS FOR: a lake preserved through a teardown,
    inspected before a new Elysium is configured on top of it.

    The structural checks still run; the ontology-aware ones are
    skipped rather than guessed at.
    """
    report = check_mirror(mirror._catalog)

    assert report.ok, report.problems
    assert report.tables_checked == 2


def test_it_reports_everything_rather_than_stopping_at_the_first(mirror):
    # An integrity problem is something a person decides about, and a
    # check that stopped at the first fault would hide the rest.
    mirror._catalog.drop_table("bronze_s.t")
    schema = {
        "Thing": {
            **SCHEMA["Thing"],
            "fields": {**SCHEMA["Thing"]["fields"], "never_synced": {"type": "data"}},
        },
    }

    report = check_mirror(mirror._catalog, schema)

    assert len(report.problems) >= 2


class TestAMissingCatalog:
    """Two very different situations that look identical from outside.

    FOUND BY A PERSON RUNNING THE SCRIPT on a machine that had never
    synced. The first version reported both as the alarming case, and
    told someone with a fresh checkout that their backup strategy had
    failed.

    NO CATALOG AND NO DATA means nobody has synced yet -- an ordinary
    state, and not an error.

    NO CATALOG BUT DATA ON DISK is the serious one: the Parquet is
    there and nothing can interpret it. Our catalog is a SQLite file
    beside the warehouse, so this is the shape that losing it takes.
    """

    @staticmethod
    def _run(mirror_dir):
        import subprocess

        return subprocess.run(
            ["python", "-m", "scripts.check_mirror", "--mirror", str(mirror_dir)],
            capture_output=True, text=True, check=False,
        )

    def test_never_synced_is_not_an_error(self, tmp_path):
        result = self._run(tmp_path / "absent")

        assert result.returncode == 0
        assert "Nothing has been synced yet" in result.stdout

    def test_never_synced_says_what_to_do(self, tmp_path):
        # A person seeing this has a next step, not a diagnosis.
        result = self._run(tmp_path / "absent")

        assert "run_sync" in result.stdout

    def test_data_without_a_catalog_is_an_error(self, mirror):
        (mirror.mirror_path / "catalog.db").unlink()

        result = self._run(mirror.mirror_path)

        assert result.returncode == 1
        assert "DATA WITHOUT A CATALOG" in result.stderr

    def test_data_without_a_catalog_explains_the_consequence(self, mirror):
        # THE CONTROL on the wording. "Missing catalog" alone would not
        # tell someone why it matters, and this is the one failure
        # where the consequence is not obvious from the symptom.
        (mirror.mirror_path / "catalog.db").unlink()

        result = self._run(mirror.mirror_path)

        assert "nothing can interpret them" in result.stderr
        assert "part of any backup" in result.stderr

    def test_the_two_cases_do_not_share_a_message(self, tmp_path, mirror):
        # The original defect, stated as a test: a fresh checkout and a
        # lost catalog must not read the same.
        fresh = self._run(tmp_path / "absent")
        (mirror.mirror_path / "catalog.db").unlink()
        lost = self._run(mirror.mirror_path)

        assert fresh.returncode != lost.returncode
        assert "part of any backup" not in fresh.stdout


class TestACountMismatchNamesItsDirection:
    """Which way the counts differ says which fault it is.

    A FIRST VERSION REPORTED BOTH as "a transform dropped rows
    silently", which is right for one and misleading for the other.
    Seen on a real deployment reporting 67 served against 7 fetched,
    where nothing had been dropped and silver was simply out of date.
    """

    @staticmethod
    def _note_for(silver, bronze, monkeypatch):
        from core.mirror import integrity

        counts = {"s.t": silver, "bronze_s.t": bronze}
        monkeypatch.setattr(
            integrity, "_row_count", lambda catalog, identifier: counts.get(identifier),
        )
        monkeypatch.setattr(
            integrity, "_partition_tables",
            lambda catalog: ({"s.t"}, {"bronze_s.t"}),
        )
        report = integrity.check_mirror(object())
        return " ".join(report.problems)

    def test_fewer_served_means_the_sync_was_refused(self, monkeypatch):
        note = self._note_for(silver=2, bronze=4, monkeypatch=monkeypatch)

        assert "refused to accept what bronze fetched" in note

    def test_more_served_means_silver_is_stale(self, monkeypatch):
        # The case a real deployment showed: bronze current, silver
        # from before the source shrank.
        note = self._note_for(silver=67, bronze=7, monkeypatch=monkeypatch)

        assert "older than bronze" in note
        assert "dropped" not in note

    def test_equal_counts_say_nothing(self, monkeypatch):
        # THE CONTROL. A note on every table would be ignored by the
        # time one mattered.
        note = self._note_for(silver=7, bronze=7, monkeypatch=monkeypatch)

        assert note == ""
