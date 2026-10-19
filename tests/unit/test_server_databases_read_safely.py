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
