"""A source that is a streaming standby, behind its primary (21 October).

The time a sync records is when its read began, and it means
"everything committed before this is in the copy": freshness is shown
from it, and the overlay of Elysium's own writes rests on it. On a
standby whose replay has fallen behind, neither holds -- its data stops
at the last change it applied. Found running Elysium against a real
streaming standby in the simulator, with replay paused.
"""

import time
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, text

from adapters.sqlalchemy_adapter import SQLAlchemyReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from scripts.run_sync import _detail_for


@pytest.fixture(scope="module")
def pair():
    from tests.postgres_server import real_postgres_standby

    primary, standby, stop = real_postgres_standby()
    primary_url = primary.replace("postgresql://", "postgresql+psycopg://")
    standby_url = standby.replace("postgresql://", "postgresql+psycopg://")
    with create_engine(primary_url).begin() as conn:
        conn.execute(text("CREATE TABLE orders (id TEXT PRIMARY KEY, v TEXT)"))
        conn.execute(text("INSERT INTO orders VALUES ('1', 'x')"))
    _caught_up(standby_url)
    yield primary_url, standby_url
    stop()


def _caught_up(url, timeout=10.0):
    deadline = time.monotonic() + timeout
    engine = create_engine(url)
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            if conn.execute(text("SELECT pg_last_wal_receive_lsn() = pg_last_wal_replay_lsn() "
                                 "AND to_regclass('orders') IS NOT NULL")).scalar():
                return
        time.sleep(0.1)
    raise AssertionError("the standby never caught up")


def _replay(url, paused):
    with create_engine(url).connect() as conn:
        conn.execute(text("SELECT pg_wal_replay_pause()" if paused
                          else "SELECT pg_wal_replay_resume()"))
        conn.commit()


def _write(url, key):
    with create_engine(url).begin() as conn:
        conn.execute(text("INSERT INTO orders VALUES (:k, 'y')"), {"k": key})


ARGS = ("p", "orders", "id", ["id", "v"], {"id": "string", "v": "string"})


def test_a_caught_up_standby_is_dated_from_the_read(pair, tmp_path):
    """THE CONTROL: an idle primary is not lag."""
    _, standby = pair
    _caught_up(standby)        # a checkpoint's WAL may be in flight
    adapter = SQLAlchemyReadAdapter({"url": standby})
    before = datetime.now(UTC)

    sync = IcebergMirrorSync(tmp_path / "m", {"p": adapter})
    result = sync.sync_table(*ARGS)

    assert adapter.source_behind() is None
    assert sync.last_synced_at("p", "orders") >= before
    assert result.behind is None


def test_a_lagging_standby_dates_the_copy_from_its_last_change(pair, tmp_path):
    primary, standby = pair
    # A DATABASE IN ANOTHER ZONE, set at the primary and replicated: what
    # psycopg hands back follows the session's zone.
    with create_engine(primary).begin() as conn:
        conn.execute(text("ALTER DATABASE postgres SET timezone = 'Asia/Tokyo'"))
    _write(primary, "before")
    _caught_up(standby)
    applied = datetime.now(UTC)
    _replay(standby, True)
    try:
        time.sleep(1.5)
        _write(primary, "unseen")                  # received, not replayed
        time.sleep(0.5)
        adapter = SQLAlchemyReadAdapter({"url": standby})

        sync = IcebergMirrorSync(tmp_path / "m", {"p": adapter})
        result = sync.sync_table(*ARGS)

        dated = sync.last_synced_at("p", "orders")
        assert dated <= applied, "dated from the standby's data, not the read"
        # AS UTC TEXT: the overlay compares it with the write log's UTC
        # stamps as strings (found in review: a Tokyo session read ahead).
        recorded = sync.catalog.load_table("p.orders").properties[
            "elysium.source_read_started_at"]
        assert recorded.endswith("+00:00") and recorded <= applied.isoformat()
        assert "PAUSED" in result.behind and "standby" in result.behind
        assert "standby" in _detail_for(result), "the Mirror screen is told why"
        ids = {r["id"] for r in sync.catalog.load_table("p.orders").scan().to_arrow().to_pylist()}
        assert "unseen" not in ids, "the copy is what the standby holds"
    finally:
        _replay(standby, False)
        with create_engine(primary).begin() as conn:
            conn.execute(text("ALTER DATABASE postgres RESET timezone"))
        _caught_up(standby)


def test_a_primary_is_never_a_standby(pair):
    primary, _ = pair

    assert SQLAlchemyReadAdapter({"url": primary}).source_behind() is None
