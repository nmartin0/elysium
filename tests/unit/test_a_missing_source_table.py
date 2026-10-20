"""A table the sync reads is no longer in the source (21 October).

Found running Elysium over a simulated world with a table renamed and
another dropped: the mirror rightly kept its last good copies, and the
reasons were "could not read the columns of 'skills': skills" on
PostgreSQL and "source column 'id' ... is gone" on SQLite. Now the sync
says the table has gone, and names the source's tables the mirror does
not hold -- where a renamed table's new name will be.
"""

import sqlite3

import pytest
from sqlalchemy import text

from adapters.csv_folder_adapter import CsvFolderAdapter
from adapters.sqlalchemy_adapter import SQLAlchemyReadAdapter
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

ARGS = ("p", "t", "id", ["id", "v"], {"id": "string", "v": "string"}, {"v": "v"})


class _NoWrites:
    def edits_touching_field(self, *_):
        return {"applied": 0, "pending": 0}


def _sqlite(tmp_path, *tables):
    db = tmp_path / "s.db"
    with sqlite3.connect(db) as conn:
        for name in tables:
            conn.execute(f"CREATE TABLE {name} (id TEXT, v TEXT)")
            conn.execute(f"INSERT INTO {name} VALUES ('1', 'x')")
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": str(db)})},
                             write_log=_NoWrites())
    return db, sync


def _change(db, *statements):
    with sqlite3.connect(db) as conn:
        for statement in statements:
            conn.execute(statement)


class TestOnSQLite:
    def test_a_dropped_table_is_named_as_gone(self, tmp_path):
        db, sync = _sqlite(tmp_path, "t")
        sync.sync_table(*ARGS)
        _change(db, "DROP TABLE t")

        with pytest.raises(ValueError) as refused:
            sync.sync_table(*ARGS)

        said = str(refused.value)
        assert "no table 't' any more" in said and "last good" in said
        assert "column 'id'" not in said

    def test_a_renamed_tables_new_name_is_among_those_named(self, tmp_path):
        db, sync = _sqlite(tmp_path, "t", "other")
        sync.sync_table(*ARGS)
        sync.sync_table("p", "other", "id", ["id", "v"], {"id": "string", "v": "string"},
                        {"v": "v"})
        _change(db, "ALTER TABLE t RENAME TO t_renamed")

        with pytest.raises(ValueError) as refused:
            sync.sync_table(*ARGS)

        said = str(refused.value)
        assert "'t_renamed'" in said and "storage.table" in said
        assert "'other'" not in said, "a table the mirror already holds is no candidate"

    def test_the_last_good_copy_is_still_served(self, tmp_path):
        db, sync = _sqlite(tmp_path, "t")
        sync.sync_table(*ARGS)
        _change(db, "DROP TABLE t")

        with pytest.raises(ValueError):
            sync.sync_table(*ARGS)

        assert sync.catalog.load_table("p.t").scan().to_arrow().num_rows == 1

    def test_a_table_that_is_there_is_not_affected(self, tmp_path):
        """THE CONTROL: an ordinary sync lists the tables and carries on."""
        _, sync = _sqlite(tmp_path, "t")

        assert sync.sync_table(*ARGS).row_count == 1

    def test_a_table_never_synced_is_a_name_to_check_not_a_table_gone(self, tmp_path):
        _, sync = _sqlite(tmp_path, "customers")

        with pytest.raises(ValueError) as refused:
            sync.sync_table(*ARGS)

        said = str(refused.value)
        assert "no table 't'." in said and "'customers'" in said and "any more" not in said

    def test_the_reader_lists_tables_and_views(self, tmp_path):
        db = tmp_path / "s.db"
        with sqlite3.connect(db) as conn:
            conn.execute("CREATE TABLE a (id TEXT)")
            conn.execute("CREATE VIEW b AS SELECT * FROM a")

        assert SQLiteReadAdapter({"path": str(db)}).tables_present() == {"a", "b"}


class TestOnlyWhenTheSourceSaysSo:
    """Found in review, 21 October: on MySQL a revoked grant hides a table
    from the listing as well, so "not listed" alone is not "gone"."""

    def test_a_refused_read_keeps_its_own_reason(self, tmp_path):
        from core.ontology.interface import StorageUnavailable

        db, sync = _sqlite(tmp_path, "t")
        sync.sync_table(*ARGS)
        adapter = sync.adapters["p"]

        def denied(table):
            raise StorageUnavailable("access denied for user 'elysium' to table 't'")

        adapter.columns_present = denied
        adapter.tables_present = lambda: {"other"}

        with pytest.raises(StorageUnavailable, match="access denied"):
            sync.sync_table(*ARGS)

    def test_on_sqlite_a_name_in_another_case_is_the_same_table(self, tmp_path):
        db, sync = _sqlite(tmp_path, "orders")
        adapter = sync.adapters["p"]
        adapter.columns_present = lambda table: set()      # as a busy file reads

        with pytest.raises(ValueError) as refused:
            sync.sync_table("p", "Orders", "id", ["id", "v"],
                            {"id": "string", "v": "string"}, {"v": "v"})

        assert "no table" not in str(refused.value)


def test_a_source_that_cannot_list_tables_says_nothing_new(tmp_path):
    """A folder cannot say which tables exist: its own reason stands."""
    assert CsvFolderAdapter({"path": tmp_path, "tables": {
        "t": {"files": "t_*.csv", "shape": "combined"}}}).tables_present() is None


@pytest.fixture(scope="module")
def postgres():
    from sqlalchemy import create_engine

    from tests.postgres_server import real_postgres

    uri, stop = real_postgres()
    url = uri.replace("postgresql://", "postgresql+psycopg://")
    with create_engine(url).begin() as conn:
        for name in ("skills", "kept"):
            conn.execute(text(f"CREATE TABLE {name} (id TEXT PRIMARY KEY, v TEXT)"))
            conn.execute(text(f"INSERT INTO {name} VALUES ('1', 'x')"))
        conn.execute(text("CREATE MATERIALIZED VIEW kept_summary AS SELECT count(*) AS n FROM kept"))
    yield url
    stop()


def test_on_postgresql_a_renamed_table_is_named_as_gone(postgres, tmp_path):
    """The case the simulated world found, on the engine it found it on."""
    from sqlalchemy import create_engine

    adapter = SQLAlchemyReadAdapter({"url": postgres})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": adapter}, write_log=_NoWrites())
    args = ("p", "skills", "id", ["id", "v"], {"id": "string", "v": "string"}, {"v": "v"})
    sync.sync_table(*args)
    with create_engine(postgres).begin() as conn:
        conn.execute(text("ALTER TABLE skills RENAME TO competencies"))

    with pytest.raises(ValueError) as refused:
        sync.sync_table(*args)

    said = str(refused.value)
    assert "no table 'skills' any more" in said and "'competencies'" in said
    assert "could not read the columns" not in said
    assert adapter.tables_present() >= {"competencies", "kept", "kept_summary"}, \
        "a materialized view is a table a source can be"
