"""PostgreSQL and MariaDB, read the way a sync reads them (19 October).

Run against the simulator's world, the SQLAlchemy adapter read both
correctly -- and showed three gaps, each only visible on a real engine:

  - MariaDB had NO QUERY TIME LIMIT. PostgreSQL's statement_timeout was
    the only one, so one slow query could hold a MariaDB sync forever.
  - MariaDB closes an idle connection after eight hours, and pooled
    connections were never recycled before that.
  - Neither session was READ ONLY. INSTALL.md asks for a SELECT-only
    account; this is the second lock, for the account given more.

A real server for each, started once per module (tests/postgres_server.py,
tests/mariadb_server.py). Neither is skipped when missing: it fails.
"""

import pytest
from sqlalchemy import text

from adapters.sqlalchemy_adapter import MYSQL_POOL_RECYCLE_SECONDS, SQLAlchemyReadAdapter
from core.ontology.interface import StorageUnavailable


@pytest.fixture(scope="module")
def mariadb():
    from tests.mariadb_server import real_mariadb

    url, stop = real_mariadb()
    owner = SQLAlchemyReadAdapter({"url": url})
    # Built through a SEPARATE, writable engine: the adapter's own refuses.
    from sqlalchemy import create_engine

    with create_engine(url).begin() as conn:
        conn.execute(text("CREATE TABLE orders (order_id VARCHAR(16) PRIMARY KEY, "
                          "total DECIMAL(19,4), placed_at DATETIME, discontinued TINYINT(1))"))
        conn.execute(text("INSERT INTO orders VALUES ('o1', 12.5000, '2026-01-01 07:00:00', 0), "
                          "('o2', 3.2500, '2026-01-02 09:30:00', 1)"))
    yield url
    owner._engine.dispose()
    stop()


@pytest.fixture(scope="module")
def postgres():
    from sqlalchemy import create_engine

    from tests.postgres_server import real_postgres

    uri, stop = real_postgres()
    url = uri.replace("postgresql://", "postgresql+psycopg://")
    with create_engine(url).begin() as conn:
        conn.execute(text("CREATE TABLE sales (sale_id TEXT PRIMARY KEY, rang_at TIMESTAMPTZ)"))
        conn.execute(text("INSERT INTO sales VALUES ('s1', '2026-01-01 00:40:00+00')"))
    yield url
    stop()


class TestMariaDB:
    def test_it_reads_one_snapshot(self, mariadb):
        adapter = SQLAlchemyReadAdapter({"url": mariadb})
        with adapter.consistent_read() as snapshot:
            rows = [row for batch in adapter.iter_all_rows("orders", ["order_id", "total"], {})
                    for row in batch]

        assert snapshot is True
        assert sorted(row["order_id"] for row in rows) == ["o1", "o2"]

    def test_a_query_past_its_time_limit_is_stopped(self, mariadb):
        adapter = SQLAlchemyReadAdapter({"url": mariadb, "query_timeout_seconds": 1})

        with adapter._engine.connect() as conn:
            limit = conn.execute(text("SELECT @@SESSION.max_statement_time")).scalar()
            assert float(limit) == 1.0
            with pytest.raises(Exception, match="max_statement_time"):
                conn.execute(text("SELECT SLEEP(5) FROM orders"))

    def test_the_session_refuses_to_write(self, mariadb):
        adapter = SQLAlchemyReadAdapter({"url": mariadb})

        with adapter._engine.connect() as conn, pytest.raises(Exception, match="(?i)read.only"):
            conn.execute(text("INSERT INTO orders VALUES ('o3', 1, NULL, 0)"))

    def test_a_consistent_read_is_still_read_only(self, mariadb):
        adapter = SQLAlchemyReadAdapter({"url": mariadb})

        with adapter.consistent_read(), pytest.raises(StorageUnavailable, match="(?i)read.only"):
            adapter._execute(text("UPDATE orders SET total = 0"))

    def test_pooled_connections_are_recycled_before_the_server_drops_them(self, mariadb):
        adapter = SQLAlchemyReadAdapter({"url": mariadb})
        with adapter._engine.connect() as conn:
            wait_timeout = conn.execute(text("SELECT @@SESSION.wait_timeout")).scalar()

        assert adapter._engine.pool._recycle == MYSQL_POOL_RECYCLE_SECONDS < int(wait_timeout)

    def test_types_as_the_source_declares_them(self, mariadb):
        types = SQLAlchemyReadAdapter({"url": mariadb}).source_column_types("orders")

        assert types["total"] == "DECIMAL(19, 4)" and types["placed_at"] == "DATETIME"


class TestPostgreSQL:
    def test_the_session_refuses_to_write(self, postgres):
        adapter = SQLAlchemyReadAdapter({"url": postgres})

        with adapter._engine.connect() as conn, pytest.raises(Exception, match="read-only transaction"):
            conn.execute(text("INSERT INTO sales VALUES ('s2', now())"))

    def test_a_consistent_read_is_still_read_only(self, postgres):
        adapter = SQLAlchemyReadAdapter({"url": postgres})

        with adapter.consistent_read() as snapshot:
            assert snapshot is True
            with pytest.raises(StorageUnavailable, match="read-only transaction"):
                adapter._execute(text("DELETE FROM sales"))

    def test_reads_still_work(self, postgres):
        adapter = SQLAlchemyReadAdapter({"url": postgres})

        assert adapter.columns_present("sales") == {"sale_id", "rang_at"}
        assert adapter.source_column_types("sales")["rang_at"] == "TIMESTAMP WITH TIME ZONE"


def test_a_sqlite_url_is_given_none_of_it(tmp_path):
    """The MySQL family's settings are set on MySQL-family connections
    only: a SQLite engine would reject `SET SESSION`."""
    adapter = SQLAlchemyReadAdapter({"url": f"sqlite:///{tmp_path / 'x.db'}"})
    adapter.health_check()

    assert adapter._mysql_family is False


class TestRowsHiddenFromTheSync:
    """PostgreSQL's row-level security, as it applies to the account a
    sync reads as (19 October). With it on and no policy for that account,
    PostgreSQL "returns no rows without raising an error" (Fivetran) -- a
    sync would copy a partial table and call it whole."""

    @pytest.fixture(scope="class")
    def server(self):
        from sqlalchemy import create_engine

        from tests.postgres_server import real_postgres

        uri, stop = real_postgres()
        owner_url = uri.replace("postgresql://", "postgresql+psycopg://")
        with create_engine(owner_url).begin() as conn:
            for statement in (
                "CREATE ROLE reader LOGIN", "CREATE ROLE bypasser LOGIN BYPASSRLS",
                "CREATE TABLE open_t (id TEXT)", "CREATE TABLE locked (id TEXT)",
                "CREATE TABLE governed (id TEXT, region TEXT)",
                "INSERT INTO locked VALUES ('a'), ('b')",
                "ALTER TABLE locked ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE governed ENABLE ROW LEVEL SECURITY",
                "CREATE POLICY west ON governed FOR SELECT USING (region = 'west')",
                "GRANT SELECT ON open_t, locked, governed TO reader, bypasser",
                "CREATE TABLE owned (id TEXT)", "ALTER TABLE owned ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE owned OWNER TO reader",
                "CREATE TABLE owned_forced (id TEXT)",
                "ALTER TABLE owned_forced ENABLE ROW LEVEL SECURITY",
                "ALTER TABLE owned_forced FORCE ROW LEVEL SECURITY",
                "ALTER TABLE owned_forced OWNER TO reader",
            ):
                conn.execute(text(statement))
        user = owner_url.split("://", 1)[1].split("@", 1)[0]

        def as_role(role):
            return SQLAlchemyReadAdapter({"url": owner_url.replace(f"://{user}@", f"://{role}@", 1)})
        yield as_role
        stop()

    def test_no_policy_means_no_rows_and_it_says_so(self, server):
        adapter = server("reader")

        warning = adapter.rows_hidden_from_this_reader("locked")

        assert adapter.read_all_rows("locked", ["id"], {}) == [], "the trap itself: nothing, no error"
        assert "NO rows" in warning and "BYPASSRLS" in warning

    def test_a_policy_is_counted(self, server):
        assert "1 policy decide" in server("reader").rows_hidden_from_this_reader("governed")

    def test_an_account_that_bypasses_it_is_not_warned(self, server):
        assert server("bypasser").rows_hidden_from_this_reader("locked") is None

    def test_the_owner_is_exempt_unless_forced(self, server):
        """PostgreSQL exempts a table's owner from its row-level security
        unless it is FORCED -- so an owner reads everything, until then."""
        owner = server("reader")

        assert owner.rows_hidden_from_this_reader("owned") is None
        assert "NO rows" in owner.rows_hidden_from_this_reader("owned_forced")

    def test_a_table_without_it_is_not_warned(self, server):
        assert server("reader").rows_hidden_from_this_reader("open_t") is None


def test_a_sync_carries_the_warning_onto_its_result(tmp_path):
    """The adapter's answer reaches the attempt the Mirror screen reads."""
    import sqlite3

    from adapters.sqlite_adapter import SQLiteReadAdapter
    from core.mirror.iceberg_sync import IcebergMirrorSync
    from scripts.run_sync import _detail_for

    class Hiding(SQLiteReadAdapter):
        def rows_hidden_from_this_reader(self, table_name):
            return f"{table_name}: rows may be hidden"

    db = tmp_path / "s.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE t (id TEXT, v TEXT)")
        conn.execute("INSERT INTO t VALUES ('1', 'x')")
    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": Hiding({"path": str(db)})})

    result = sync.sync_table("s", "t", "id", ["id", "v"])

    assert result.hidden_rows == "t: rows may be hidden"
    assert "rows may be hidden" in _detail_for(result)


def test_a_refused_empty_read_names_the_likely_cause_first(tmp_path):
    """FOUND AGAINST THE SIMULATOR: row-level security switched on made
    the source return nothing; the mass-deletion guard rightly refused --
    and its only advice was `--accept-deletions`, which would have
    replaced the whole copy with an empty one."""
    import sqlite3

    from adapters.sqlite_adapter import SQLiteReadAdapter
    from core.mirror.iceberg_sync import IcebergMirrorSync

    class Hiding(SQLiteReadAdapter):
        warn = None

        def rows_hidden_from_this_reader(self, table_name):
            return self.warn

    db = tmp_path / "s.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE t (id TEXT, v TEXT)")
        conn.executemany("INSERT INTO t VALUES (?, ?)", [(str(i), "x") for i in range(10)])
    adapter = Hiding({"path": str(db)})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": adapter})
    sync.sync_table("s", "t", "id", ["id", "v"])
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM t")
    adapter.warn = "t has row-level security switched on."

    with pytest.raises(Exception) as refused:
        sync.sync_table("s", "t", "id", ["id", "v"])

    message = str(refused.value)
    assert "THE LIKELY CAUSE: t has row-level security" in message
    assert message.index("LIKELY CAUSE") < message.index("--accept-deletions")
