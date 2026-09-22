"""
Read-your-writes against the mirror: every edit since the sync, and a
sync timestamp that leaves no window (001's F-26 and F-29, fixed
together because they are two halves of one guarantee).

F-26, MEASURED: the single-object overlay took the LATEST applied entry
only (LIMIT 1). An edit carries just the fields it changed, so editing
a name and then a region reverted the name on read until the next sync.
The flat-list counterpart already merged -- the two paths disagreed.

F-29, MEASURED: last_synced_at() reported the snapshot's COMMIT time,
later than the source read. A write applied while the sync ran was in
neither the mirror (read before it) nor the overlay (excluded as older
than the commit): a 2 s read left a 2.08 s window.
"""

import sqlite3
import time
from datetime import UTC, datetime, timedelta

import pytest

from core.mirror.iceberg_sync import SOURCE_READ_PROPERTY, IcebergMirrorSync
from core.ontology.write_log import WriteLogWriter

BEFORE = (datetime.now(UTC) - timedelta(hours=1)).isoformat()


@pytest.fixture
def log(tmp_path):
    return WriteLogWriter(tmp_path / "write_log.db")


def _applied(log, changes):
    log_id = log.log_pending_update("Customer", "c1", changes, {}, "alice", "edit", operation="update")
    log.mark_applied(log_id)
    time.sleep(0.005)  # distinct created_at values
    return log_id


class TestEveryEditSinceTheSync:
    def test_two_edits_to_different_fields_both_survive(self, log):
        _applied(log, {"name": "Ada"})
        _applied(log, {"region": "us-east"})

        assert log.get_applied_changes_since("Customer", "c1", BEFORE) == {
            "name": "Ada", "region": "us-east",
        }

    def test_the_later_edit_to_the_SAME_field_wins(self, log):
        _applied(log, {"name": "First"})
        _applied(log, {"name": "Second"})

        assert log.get_applied_changes_since("Customer", "c1", BEFORE) == {"name": "Second"}

    def test_it_agrees_with_the_search_overlay(self, log):
        """The two paths disagreed: one merged, one did not."""
        _applied(log, {"name": "Ada"})
        _applied(log, {"region": "us-east"})

        flat = {(e["object_type"], e["object_id"]): e["changes"]
                for e in log.get_all_applied_changes_since(BEFORE)}
        assert flat[("Customer", "c1")] == log.get_applied_changes_since("Customer", "c1", BEFORE)

    def test_entries_already_mirrored_are_still_excluded(self, log):
        _applied(log, {"name": "Ada"})
        later = datetime.now(UTC).isoformat()
        _applied(log, {"region": "us-east"})

        assert log.get_applied_changes_since("Customer", "c1", later) == {"region": "us-east"}

    def test_nothing_since_is_still_None(self, log):
        _applied(log, {"name": "Ada"})

        assert log.get_applied_changes_since("Customer", "c1", datetime.now(UTC).isoformat()) is None


class Slow:
    """A source read that takes measurable time, as a real one does."""

    def __init__(self, inner, seconds=1.0):
        self._inner, self._seconds = inner, seconds
        self.read_started_at = None

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def read_all_rows(self, *args, **kwargs):
        self.read_started_at = datetime.now(UTC)
        time.sleep(self._seconds)
        return self._inner.read_all_rows(*args, **kwargs)


@pytest.fixture
def slow_sync(tmp_path):
    from adapters.sqlite_adapter import SQLiteReadAdapter

    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', 'Ada')")
    conn.commit()
    conn.close()
    adapter = Slow(SQLiteReadAdapter({"path": source}))
    return IcebergMirrorSync(tmp_path / "mirror", {"primary": adapter}), adapter


def _sync(sync):
    return sync.sync_table("primary", "customers", "customer_id", ["customer_id", "name"],
                           {"customer_id": "string", "name": "string"})


class TestTheSyncTimestamp:
    def test_it_is_not_later_than_the_source_read(self, slow_sync):
        """THE WINDOW, CLOSED: everything after this instant is still
        overlaid. Before, the commit time left 2.08 s uncovered."""
        sync, adapter = slow_sync
        _sync(sync)

        reported = sync.last_synced_at("primary", "customers")

        assert reported <= adapter.read_started_at

    def test_and_earlier_than_the_commit(self, slow_sync):
        sync, _ = slow_sync
        _sync(sync)
        table = sync._catalog.load_table("primary.customers")
        committed = datetime.fromtimestamp(table.current_snapshot().timestamp_ms / 1000, tz=UTC)

        assert sync.last_synced_at("primary", "customers") < committed

    def test_the_table_records_it(self, slow_sync):
        sync, _ = slow_sync
        _sync(sync)

        assert SOURCE_READ_PROPERTY in sync._catalog.load_table("primary.customers").properties

    def test_a_table_without_it_falls_back_to_the_commit_time(self, slow_sync):
        """A table synced before the property existed still answers."""
        sync, _ = slow_sync
        _sync(sync)
        table = sync._catalog.load_table("primary.customers")
        with table.transaction() as tx:
            tx.remove_properties(SOURCE_READ_PROPERTY)
        committed = datetime.fromtimestamp(
            sync._catalog.load_table("primary.customers").current_snapshot().timestamp_ms / 1000, tz=UTC)

        assert sync.last_synced_at("primary", "customers") == committed
