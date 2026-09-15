"""
A sync that finds nothing changed writes nothing.

MEASURED, AND THIS IS THE LARGEST STORAGE WIN AVAILABLE. Iceberg's
copy-on-write makes every snapshot a COMPLETE copy, so a nightly sync
of a table nobody edited was writing the whole table again to record
that it was identical. Thirty identical syncs of a 50,000-row table:

    before: 27.2 MB across 65 snapshots, all holding the same data
    after :  0.9 MB across  1 snapshot

pyiceberg 0.12 has no snapshot expiry -- checked, not assumed -- so
nothing reclaims those afterwards. The cheapest fix is not to create
them, and it is the safest too: writing nothing is never wrong, where
deleting a snapshot can be.

IDEMPOTENCY IS THE PATTERN THIS SATISFIES: a pipeline "produces the
same result regardless of how many times it is executed with the same
input". Re-running a sync should be free, and now nearly is.

COMPARED ON CONTENT, not on a source timestamp, because our sources
have none -- verified: `customers` has no timestamp at all, and
`transactions` carries only a business date that does not move when a
row is edited.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

COLUMNS = ["id", "a"]
TYPES = {"id": "string", "a": "string"}


@pytest.fixture
def sync(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
    connection.executemany("INSERT INTO t VALUES (?, ?)", [("1", "x"), ("2", "y")])
    connection.commit()
    connection.close()
    mirror = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})
    mirror.source_path = source
    return mirror


def _change(source, value):
    connection = sqlite3.connect(source)
    connection.execute("UPDATE t SET a = ? WHERE id = '1'", (value,))
    connection.commit()
    connection.close()


def _snapshots(sync, identifier):
    return len(list(sync._catalog.load_table(identifier).snapshots()))


def test_a_second_identical_sync_adds_no_snapshot(sync):
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)
    after_first = _snapshots(sync, "s.t")

    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    assert _snapshots(sync, "s.t") == after_first


def test_bronze_skips_too(sync):
    # Bronze needs it MORE: it stores every column rather than the
    # declared ones, so its snapshots are the larger ones. With silver
    # skipping and bronze not, 30 identical syncs still grew to 13.1 MB.
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)
    after_first = _snapshots(sync, "bronze_s.t")

    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    assert _snapshots(sync, "bronze_s.t") == after_first


def test_a_real_change_is_still_recorded(sync):
    """THE CONTROL, and the one that matters.

    A sync that skipped when data HAD changed would leave the mirror
    silently describing a source that has moved on -- far worse than
    the storage it saves.
    """
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)
    after_first = _snapshots(sync, "s.t")

    _change(sync.source_path, "CHANGED")
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    assert _snapshots(sync, "s.t") > after_first
    rows = sync._catalog.load_table("s.t").scan().to_arrow().to_pydict()
    assert "CHANGED" in rows["a"]


def test_the_row_count_is_still_reported_when_nothing_was_written(sync):
    # A caller asking "how many rows does the mirror hold" must get the
    # real answer, not zero because this particular sync wrote nothing.
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    result = sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    assert result.row_count == 2


def test_a_row_added_to_the_source_is_not_missed(sync):
    # The cheap row-count check catches this before comparing values,
    # which is the common case for a growing table.
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    connection = sqlite3.connect(sync.source_path)
    connection.execute("INSERT INTO t VALUES ('3', 'z')")
    connection.commit()
    connection.close()
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    assert sync._catalog.load_table("s.t").scan().to_arrow().num_rows == 3


def test_row_order_alone_does_not_count_as_a_change(sync):
    """Iceberg does not promise row order across snapshots.

    Comparing unsorted would make every sync look changed, which would
    defeat the whole feature while appearing to work.
    """
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)
    after_first = _snapshots(sync, "s.t")

    # Rewrite the same rows in the opposite order.
    connection = sqlite3.connect(sync.source_path)
    connection.execute("DELETE FROM t")
    connection.executemany("INSERT INTO t VALUES (?, ?)", [("2", "y"), ("1", "x")])
    connection.commit()
    connection.close()
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    assert _snapshots(sync, "s.t") == after_first
