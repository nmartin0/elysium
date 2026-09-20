"""
When a mirrored table's data changed, from Iceberg's own record.

READ FROM METADATA, NOT BY SCANNING. Iceberg commits a snapshot per
change and keeps them, with a timestamp, an operation and a row count.
The history is already there; nothing new is stored.

WHY IT MATTERS: the mirror panel shows the CURRENT state and said
nothing about how it got there. An administrator seeing "7 rows,
synced an hour ago" could not tell a table that changed once from one
that changed nine times.

AND IT IS WHAT A ROLLBACK WOULD NEED. Knowing which snapshot is being
served is the question "roll back to yesterday" starts from.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from api.routes import _recent_snapshots
from core.mirror.iceberg_sync import IcebergMirrorSync


@pytest.fixture
def synced(tmp_path):
    """A mirror with real history: three syncs, two of which changed
    the data."""
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
    conn.execute("INSERT INTO t VALUES ('1', 'first')")
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(
        tmp_path / "m", {"s": SQLiteReadAdapter({"path": source})},
    )
    columns, types = ["id", "a"], {"id": "string", "a": "string"}
    sync.sync_table("s", "t", "id", columns, types)

    conn = sqlite3.connect(source)
    conn.execute("UPDATE t SET a = 'second' WHERE id = '1'")
    conn.commit()
    conn.close()
    sync.sync_table("s", "t", "id", columns, types)

    return sync


class TestItReadsTheHistory:
    def test_a_changed_table_has_more_than_one_snapshot(self, synced):
        history = _recent_snapshots(synced.catalog, "s.t")

        assert len(history) > 1

    def test_the_newest_is_first(self, synced):
        history = _recent_snapshots(synced.catalog, "s.t")

        assert history[0]["at"] >= history[-1]["at"]

    def test_exactly_one_is_current(self, synced):
        """A HISTORY WITHOUT A CURRENT MARKER is a list of dates. The
        point of showing it is knowing where you are in it, which is
        also where a rollback would start."""
        history = _recent_snapshots(synced.catalog, "s.t")

        assert sum(1 for entry in history if entry["current"]) == 1

    def test_each_entry_carries_its_row_count(self, synced):
        history = _recent_snapshots(synced.catalog, "s.t")

        assert history[0]["rows"] == 1

    def test_the_operation_is_a_plain_word(self, synced):
        """str() BECAUSE IT IS AN ENUM. "Operation.APPEND" reads worse
        than "APPEND" in a panel, and serialising the enum object
        would not reach the browser at all."""
        history = _recent_snapshots(synced.catalog, "s.t")

        assert history[0]["operation"] in {"APPEND", "OVERWRITE", "DELETE",
                                            "REPLACE"}


class TestItIsBounded:
    def test_it_returns_at_most_the_limit(self, synced):
        """A LONG-RUNNING DEPLOYMENT ACCUMULATES SNAPSHOTS -- nothing
        expires them, which is its own backlog item -- and a panel
        listing hundreds teaches less than one listing the last
        handful."""
        assert len(_recent_snapshots(synced.catalog, "s.t", limit=1)) == 1


class TestAMissingTableCostsItsOwnRow:
    def test_it_returns_nothing_rather_than_raising(self, synced):
        """THIS DECORATES A PANEL. A missing history should cost its
        own row and not the screen; `check_mirror` is what reports a
        table that has genuinely gone."""
        assert _recent_snapshots(synced.catalog, "no_such.table") == []
