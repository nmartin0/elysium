"""One consistent read per silo per run (R4).

AGAINST A REAL POSTGRESQL (tests/postgres_server.py), because the
property is the database's: a REPEATABLE READ transaction sees the
source as of its first statement, without blocking the source's writers.
"""

import psycopg
import pytest

from adapters.sqlalchemy_adapter import SQLAlchemyReadAdapter
from core.ontology.interface import StorageUnavailable
from scripts.run_sync import _by_silo, _consistent_read


@pytest.fixture(scope="module")
def postgres():
    from tests.postgres_server import real_postgres

    uri, stop = real_postgres()
    with psycopg.connect(uri) as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE customers (id text primary key)")
        cur.execute("CREATE TABLE orders (id text primary key, customer_id text)")
        cur.execute("INSERT INTO customers VALUES ('c1')")
        cur.execute("INSERT INTO orders VALUES ('o1', 'c1')")
        conn.commit()
    yield uri
    stop()


def _adapter(uri):
    return SQLAlchemyReadAdapter({"url": uri.replace("postgresql://", "postgresql+psycopg://")})


def _write(uri, *statements):
    with psycopg.connect(uri) as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
        conn.commit()


def test_a_write_between_two_reads_is_not_seen_inside_the_snapshot(postgres):
    """THE POINT: a customer and their new order, written between the
    two reads, must arrive together or not at all."""
    adapter = _adapter(postgres)

    with adapter.consistent_read() as consistent:
        customers = adapter.read_all_rows("customers", ["id"], {})
        _write(postgres, "INSERT INTO customers VALUES ('c2')",
               "INSERT INTO orders VALUES ('o2', 'c2')")
        orders = adapter.read_all_rows("orders", ["id", "customer_id"], {})
    after = adapter.read_all_rows("orders", ["id", "customer_id"], {})

    assert consistent is True
    assert {row["id"] for row in customers} == {"c1"}
    assert {row["id"] for row in orders} == {"o1"}, "the order arrived without its customer"
    # THE CONTROL: outside the snapshot, the write is there.
    assert {row["id"] for row in after} == {"o1", "o2"}


def test_a_failed_read_does_not_poison_the_rest_of_the_snapshot(postgres):
    """PostgreSQL aborts a whole transaction on any error; each read runs
    in a savepoint, so only the failed one is lost."""
    adapter = _adapter(postgres)

    with adapter.consistent_read():
        with pytest.raises(StorageUnavailable):
            adapter.read_all_rows("no_such_table", ["id"], {})
        rows = adapter.read_all_rows("customers", ["id"], {})

    assert rows


def test_a_dialect_that_cannot_snapshot_without_blocking_says_so(tmp_path):
    """SQLite would hold a lock its own writers wait on."""
    adapter = SQLAlchemyReadAdapter({"url": f"sqlite:///{tmp_path / 'x.db'}"})

    with adapter.consistent_read() as consistent:
        assert consistent is False


class TestTheRun:
    def test_targets_are_grouped_by_silo_in_first_seen_order(self):
        class T:
            def __init__(self, silo, table):
                self.silo_name, self.table_name = silo, table

        grouped = _by_silo([T("a", "1"), T("b", "1"), T("a", "2")])

        assert [(silo, [t.table_name for t in ts]) for silo, ts in grouped] == [
            ("a", ["1", "2"]), ("b", ["1"])]

    def test_a_snapshot_that_cannot_open_falls_back_rather_than_failing(self, capsys):
        class Broken:
            def consistent_read(self):
                raise StorageUnavailable("down")

        with _consistent_read(Broken()) as consistent:
            assert consistent is False
        assert "reading table by table" in capsys.readouterr().err

    def test_a_real_sync_says_how_each_silo_was_read(self, synced_deployment):
        """The shipped deployment's silos are SQLite: table by table."""
        import contextlib
        import io

        from scripts.run_sync import run_sync

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            run_sync(synced_deployment)

        assert "reading primary_sql table by table" in printed.getvalue()


def test_the_run_opens_one_snapshot_per_silo_around_its_tables(synced_deployment, monkeypatch):
    """THE WIRING: every table of a silo is read inside that silo's one
    consistent read, entered once -- recorded by an adapter that reports
    whether a read happened inside it."""
    import contextlib
    import io

    from adapters.sqlite_adapter import SQLiteReadAdapter
    from scripts.run_sync import run_sync

    entered, reads = [], []
    inside = {"now": None}

    @contextlib.contextmanager
    def recording(self):
        entered.append(self.db_path.name)
        inside["now"] = self.db_path.name
        try:
            yield True
        finally:
            inside["now"] = None

    original = SQLiteReadAdapter.read_all_rows

    def read(self, table_name, columns, type_config):
        reads.append((self.db_path.name, inside["now"]))
        return original(self, table_name, columns, type_config)

    monkeypatch.setattr(SQLiteReadAdapter, "consistent_read", recording)
    monkeypatch.setattr(SQLiteReadAdapter, "read_all_rows", read)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        run_sync(synced_deployment)

    assert len(entered) == len(set(entered)), "a silo's snapshot was opened twice"
    assert reads and all(db == held for db, held in reads), reads
    assert "as one consistent snapshot" in printed.getvalue()
