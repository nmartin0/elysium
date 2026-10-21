"""The overlay of Elysium's own writes runs from each type's data, not
the deployment's oldest table (21 October).

WHAT WAS WRONG. Read-your-writes lays an applied write over the mirror's
copy until the copy catches up, and "catches up" was ONE time for the
whole deployment: the oldest read of any table. One table behind -- a
standby with replay paused -- held it back for every type, and in a type
read from a current source a write Elysium made earlier was laid over a
newer change made directly at the source: a stale value shown. And the
time came from silver, though readers are served gold; a refused gold
build left gold older than its silver, and the overlay began too late.

NOW each gold publication records when the data it was built from was
read (core/mirror/gold.py, DATA_AS_OF_PROPERTY), and the overlay for a
type runs from that.
"""

import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

import scripts.run_sync as run_sync
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import DATA_AS_OF_PROPERTY
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter

TYPES = {
    name: {"id_field": "id", "security": {"field": "region"},
           "storage": {"silo": "p", "table": name.lower(), "id_column": "id"},
           "fields": {"id": {"type": "data"}, "v": {"type": "data"},
                      "region": {"type": "data"}}}
    for name in ("Alpha", "Beta")
}


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    with closing(sqlite3.connect(source)) as conn, conn:
        for table in ("alpha", "beta"):
            conn.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, v TEXT, region TEXT)")
            conn.execute(f"INSERT INTO {table} VALUES ('x','1','us-west')")
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})
    for table in ("alpha", "beta"):
        sync.sync_table("p", table, "id", ["id", "v", "region"], {})
    sync.config = SimpleNamespace(schema=TYPES, identity_inference=False,
                                  retain_publications=30, mirror_storage={})
    return sync, tmp_path


def _recorded(sync, object_type):
    return sync.catalog.load_table(f"gold.{object_type}").properties.get(DATA_AS_OF_PROPERTY)


def _read_at(sync, table):
    return sync.last_synced_at("p", table).isoformat()


class TestGoldRecordsWhenItsDataWasRead:
    def test_a_publication_carries_its_tables_read_time(self, deployment):
        sync, data_dir = deployment

        run_sync._build_gold(sync, sync.config, data_dir)

        assert _recorded(sync, "Alpha") == _read_at(sync, "alpha")
        assert _recorded(sync, "Beta") == _read_at(sync, "beta")

    def test_the_same_data_read_again_is_as_of_the_new_read(self, deployment):
        """Gold unchanged, its inputs the same -- but read again later,
        and found the same: it is as current as that read."""
        sync, data_dir = deployment
        run_sync._build_gold(sync, sync.config, data_dir)
        before = _recorded(sync, "Alpha")

        sync.sync_table("p", "alpha", "id", ["id", "v", "region"], {})
        run_sync._build_gold(sync, sync.config, data_dir)

        assert _recorded(sync, "Alpha") == _read_at(sync, "alpha") > before

    def test_a_republication_of_changed_data_carries_the_new_read(self, deployment, tmp_path):
        """The second path through build_gold: an existing publication,
        rebuilt on a branch and audited."""
        sync, data_dir = deployment
        run_sync._build_gold(sync, sync.config, data_dir)
        with closing(sqlite3.connect(tmp_path / "s.db")) as conn, conn:
            conn.execute("UPDATE alpha SET v = '2'")
        sync.sync_table("p", "alpha", "id", ["id", "v", "region"], {})

        run_sync._build_gold(sync, sync.config, data_dir)

        assert _recorded(sync, "Alpha") == _read_at(sync, "alpha")

    def test_a_type_of_several_tables_is_as_old_as_its_oldest(self):
        times = {"p.a": "2026-01-02T00:00:00+00:00", "p.b": "2026-01-01T00:00:00+00:00"}

        class Sync:
            def last_synced_at(self, silo, table):
                from datetime import datetime
                return datetime.fromisoformat(times[f"{silo}.{table}"])

        assert run_sync._data_as_of(Sync(), {"p.a", "p.b"}) == "2026-01-01T00:00:00+00:00"

    def test_a_table_never_read_leaves_the_time_unknown(self):
        class Sync:
            def last_synced_at(self, silo, table):
                return None

        assert run_sync._data_as_of(Sync(), {"p.a"}) is None

    def test_a_type_not_rebuilt_keeps_the_time_of_what_it_serves(self, deployment):
        """Its table failed: gold still serves the old data, as of then."""
        sync, data_dir = deployment
        run_sync._build_gold(sync, sync.config, data_dir)
        before = _recorded(sync, "Alpha")

        sync.sync_table("p", "beta", "id", ["id", "v", "region"], {})
        run_sync._build_gold(sync, sync.config, data_dir, unsynced={"p.alpha"})

        assert _recorded(sync, "Alpha") == before
        assert _recorded(sync, "Beta") == _read_at(sync, "beta")

    def test_the_loader_reads_each_types_time(self, deployment):
        from core.deployment_loader import _gold_data_as_of

        sync, data_dir = deployment
        run_sync._build_gold(sync, sync.config, data_dir)

        found = _gold_data_as_of(SimpleNamespace(schema=TYPES, mirror_storage={}), data_dir)

        assert found == {"Alpha": _read_at(sync, "alpha"), "Beta": _read_at(sync, "beta")}


EARLY = "2000-01-01T00:00:00+00:00"       # the deployment's oldest table
LATE = "2999-01-01T00:00:00+00:00"        # a type read after the write


def _mediator(log, by_type):
    mediator = DataMediator.__new__(DataMediator)
    mediator.write_log = log
    mediator.mirror_synced_at = EARLY
    mediator.mirror_synced_at_by_type = by_type
    return mediator


class TestTheOverlayRunsFromEachTypesData:
    @pytest.fixture
    def log(self, tmp_path):
        log = WriteLogWriter(tmp_path / "wl.db")
        for object_type in ("Alpha", "Beta"):
            log.mark_applied(log.log_pending_update(object_type, "x", {"v": "mine"},
                                                    {"v": "1"}, "u", "t"))
        return log

    def test_a_type_read_after_the_write_serves_its_own_data(self, log):
        """THE BUG: Alpha was read after Elysium's write, so its copy holds
        the source's newer value; the write is no longer laid over it."""
        mediator = _mediator(log, {"Alpha": LATE})

        assert mediator.overlaid_fields("Alpha", "x", ["v"]) == {}
        assert mediator._overlay_since("Alpha") == LATE

    def test_a_type_behind_still_has_the_write_laid_over_it(self, log):
        """THE CONTROL, and the type with nothing recorded: the deployment's
        oldest table, as before."""
        mediator = _mediator(log, {"Alpha": LATE})

        assert mediator.overlaid_fields("Beta", "x", ["v"]) == {"v": "unsynced"}

    def test_a_live_deployment_overlays_nothing(self, log):
        mediator = _mediator(log, {"Alpha": LATE})
        mediator.mirror_synced_at = None

        assert mediator._overlay_since("Alpha") is None


class TestAWriteIsTimedWhenItIsApplied:
    """Found in review, 21 October: the overlay compared when a write was
    ASKED FOR, and a sync whose read began between asking and applying
    held a copy without the write yet counted as newer -- the write was
    hidden until the next sync. Per-type times made it likelier, by
    removing the deployment-wide hold-back that had mostly masked it."""

    def test_a_write_applied_after_a_read_began_is_still_laid_over_it(self, tmp_path):
        from datetime import UTC, datetime

        log = WriteLogWriter(tmp_path / "wl.db")
        asked = log.log_pending_update("Alpha", "x", {"v": "mine"}, {"v": "1"}, "u", "t")
        read_began = datetime.now(UTC).isoformat()      # the copy has no "mine"
        log.mark_applied(asked)

        mediator = _mediator(log, {"Alpha": read_began})

        assert mediator.overlaid_fields("Alpha", "x", ["v"]) == {"v": "unsynced"}
        assert [e["object_id"] for e in log.get_all_applied_changes_since(read_began)] == ["x"]

    def test_an_entry_from_before_the_record_is_timed_when_it_was_asked(self, tmp_path):
        log = WriteLogWriter(tmp_path / "wl.db")
        log.mark_applied(log.log_pending_update("Alpha", "x", {"v": "mine"}, {"v": "1"}, "u", "t"))
        with closing(sqlite3.connect(tmp_path / "wl.db")) as conn, conn:
            conn.execute("UPDATE write_log SET applied_at = NULL")

        assert _mediator(log, {"Alpha": EARLY}).overlaid_fields("Alpha", "x", ["v"]) == \
            {"v": "unsynced"}
        assert _mediator(log, {"Alpha": LATE}).overlaid_fields("Alpha", "x", ["v"]) == {}

    def test_an_existing_write_log_gains_the_column(self, tmp_path):
        path = tmp_path / "old.db"
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute(
                "CREATE TABLE write_log (id TEXT PRIMARY KEY, object_type TEXT NOT NULL, "
                "object_id TEXT NOT NULL, operation TEXT NOT NULL, changes TEXT NOT NULL, "
                "expected_current_values TEXT NOT NULL, status TEXT NOT NULL, "
                "user_id TEXT NOT NULL, description TEXT NOT NULL, created_at TEXT NOT NULL, "
                "batch_id TEXT)")

        log = WriteLogWriter(path)
        log.mark_applied(log.log_pending_update("Alpha", "x", {"v": "m"}, {"v": "1"}, "u", "t"))

        with closing(sqlite3.connect(path)) as conn, conn:
            assert conn.execute("SELECT applied_at FROM write_log").fetchone()[0] is not None
