"""Realism options on the database servers (REAL_SOURCES.md P1-P4, M2-M4).

Each is switched on in a pack and checked as a consumer meets it: through
the reader account the world publishes, against the real engine.
"""

import textwrap
import time

import pytest
from simulator.control import apply_drift
from simulator.relational import fetch_all
from worlds import running_world

pytestmark = pytest.mark.postgres

PG = textwrap.dedent("""
    pack: pg_realism
    silos:
      ops:
        kind: postgresql
        database: ops
        options:
          timezone: America/New_York
          reader_default_privileges: false
          row_security: [secrets]
          reader_statement_timeout_ms: 300
          reader_idle_session_timeout_ms: 700
    schemas:
      ops:
        tables:
          orders:
            columns:
              order_id: {type: text, length: 64, primary_key: true, nullable: false}
          secrets:
            columns:
              secret_id: {type: text, length: 64, primary_key: true, nullable: false}
    seed:
      - table: ops.orders
        count: 3
        columns:
          order_id: {generator: id, prefix: o}
      - table: ops.secrets
        count: 3
        columns:
          secret_id: {generator: id, prefix: s}
    """)

PLAIN_PG = textwrap.dedent("""
    pack: pg_plain
    silos:
      ops: {kind: postgresql, database: ops}
    schemas:
      ops:
        tables:
          orders:
            columns:
              order_id: {type: text, length: 64, primary_key: true, nullable: false}
    """)


def _pg_reader(world):
    import psycopg

    d = world.connections()["ops"].details
    return psycopg.connect(host=d["host"], port=d["port"], dbname=d["database"],
                           user=d["user"], password=d["password"], autocommit=True)


@pytest.fixture(scope="module")
def pg_world(tmp_path_factory, postgres_binaries):
    with running_world(tmp_path_factory.mktemp("pg"), PG, seed=2) as built:
        yield built


def test_postgresql_is_utc_unless_a_pack_says_otherwise(tmp_path, postgres_binaries):
    # Cannot fail on a host whose own zone is UTC, as the one this was
    # written on is: initdb would copy UTC anyway. It has teeth only on a
    # machine in another zone. The test below, which sets a zone, is the
    # one that proves the setting reaches the server.
    with running_world(tmp_path, PLAIN_PG) as built, _pg_reader(built) as conn:
        assert conn.execute("SHOW timezone").fetchone()[0] == "UTC"


def test_the_time_zone_a_pack_sets_is_the_servers(pg_world):
    with _pg_reader(pg_world) as conn:
        assert conn.execute("SHOW timezone").fetchone()[0] == "America/New_York"


def test_row_security_with_no_policy_shows_the_reader_nothing_and_says_nothing(pg_world):
    with _pg_reader(pg_world) as conn:
        seen = conn.execute("SELECT count(*) FROM secrets").fetchone()[0]
        orders = conn.execute("SELECT count(*) FROM orders").fetchone()[0]
    written = fetch_all(pg_world.silo("ops"), "ops", "SELECT count(*) FROM secrets")[0][0]

    assert (seen, orders, written) == (0, 3, 3)


def test_a_long_statement_is_cancelled_for_the_reader(pg_world):
    import psycopg

    with _pg_reader(pg_world) as conn, pytest.raises(psycopg.errors.QueryCanceled):
        conn.execute("SELECT pg_sleep(2)")


def test_an_idle_reader_session_is_ended(pg_world):
    import psycopg

    conn = _pg_reader(pg_world)
    try:
        time.sleep(1.5)
        with pytest.raises(psycopg.OperationalError):
            conn.execute("SELECT 1")
    finally:
        conn.close()


def test_a_table_added_later_is_refused_without_default_privileges(pg_world):
    # Last in the module: it changes the world's schema.
    import psycopg

    apply_drift(pg_world, "add_table", {"table": "ops.refunds",
                                        "columns": {"refund_id": {"type": "text",
                                                                  "length": 64}}})
    with _pg_reader(pg_world) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("SELECT count(*) FROM refunds")


MARIA = textwrap.dedent("""
    pack: maria_realism
    silos:
      shop:
        kind: mariadb
        database: shop
        options:
          time_zone: "-05:00"
          reader_wait_timeout_seconds: 1
          reader_max_statement_seconds: 0.3
          zero_dates: true
    schemas:
      shop:
        tables:
          orders:
            columns:
              order_id:   {type: text, length: 64, primary_key: true, nullable: false}
              shipped_on: {type: date}
              packed_at:  {type: timestamp}
    seed:
      - table: shop.orders
        count: 3
        columns:
          order_id:   {generator: id, prefix: o}
          shipped_on: {generator: constant, value: null}
    """)


def _maria_reader(world):
    import pymysql

    d = world.connections()["shop"].details
    return pymysql.connect(host=d["host"], port=d["port"], database=d["database"],
                           user=d["user"], password=d["password"])


@pytest.fixture(scope="module")
def maria_world(tmp_path_factory, mariadb_binaries, postgres_binaries):
    with running_world(tmp_path_factory.mktemp("maria"), MARIA, seed=2) as built:
        yield built


def test_mariadb_sessions_are_in_the_zone_a_pack_sets(maria_world):
    conn = _maria_reader(maria_world)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT @@session.time_zone")
            assert cursor.fetchone()[0] == "-05:00"
    finally:
        conn.close()


def test_the_reader_is_disconnected_when_idle_and_the_business_is_not(maria_world):
    import pymysql

    conn = _maria_reader(maria_world)
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT @@session.wait_timeout")
            assert cursor.fetchone()[0] == 1
        time.sleep(2.5)
        with pytest.raises(pymysql.err.OperationalError), conn.cursor() as cursor:
            cursor.execute("SELECT 1")
    finally:
        conn.close()
    own = fetch_all(maria_world.silo("shop"), "shop", "SELECT @@session.wait_timeout")[0][0]
    assert own == 28800, "init_connect does not reach the business's superuser"


def test_a_long_statement_is_stopped_for_the_reader(maria_world):
    import pymysql

    conn = _maria_reader(maria_world)
    try:
        with pytest.raises(pymysql.err.OperationalError) as stopped, conn.cursor() as cursor:
            # SLEEP, not BENCHMARK: measured, a BENCHMARK cut off at the limit
            # returns 0 rather than raising, where SLEEP raises 1969.
            cursor.execute("SELECT SLEEP(2)")
        assert stopped.value.args[0] == 1969       # max_statement_time exceeded
    finally:
        conn.close()


def test_the_business_writes_zero_dates_where_it_has_none(maria_world):
    zero = fetch_all(maria_world.silo("shop"), "shop",
                     "SELECT count(*) FROM orders WHERE shipped_on = '0000-00-00'")[0][0]
    nulls = fetch_all(maria_world.silo("shop"), "shop",
                      "SELECT count(*) FROM orders WHERE shipped_on IS NULL")[0][0]

    assert (zero, nulls) == (3, 0)


def test_a_date_the_business_leaves_out_is_written_as_zero_too(maria_world):
    # Found 20 October by the first run of Elysium over retail: an order
    # is created without dispatched_at, and with only explicit Nones
    # replaced no zero date was ever written.
    zero = fetch_all(maria_world.silo("shop"), "shop",
                     "SELECT count(*) FROM orders WHERE packed_at = '0000-00-00 00:00:00'")[0][0]

    assert zero == 3
