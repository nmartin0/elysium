"""
Tests for the invariant assertions guarding Points 1-3 of the machinery
audit.

WHY ASSERTIONS RATHER THAN RAISES. Each condition below is one the code
believes is IMPOSSIBLE, not one a caller can provoke. A bad argument
gets a real exception with a clear message (this project does that
throughout); an assert marks a place where the program's own reasoning
has broken down, and there is no sensible recovery -- only stopping
before the damage spreads.

They are deliberately placed where silent corruption would otherwise be
UNRECOVERABLE or UNDIAGNOSABLE:
  - a batch marked applied while a sub-write never ran: nothing revisits
    it afterwards, so the loss is permanent
  - a write-log row marked applied with storages unwritten: reads then
    report values that do not exist, with nothing left pending
  - a sync writing a different row count than it read: reports success
    with quietly incomplete data
  - a duplicate in a lock set: threading.Lock is not reentrant, so it
    HANGS rather than raising -- the hardest possible failure to
    diagnose from a stack trace

Nothing runs Python with -O in this project (verified directly), so
these are live in production, which is the point.
"""

import sqlite3

import pytest

import core.mirror.iceberg_sync as iceberg_sync_module
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.ontology.mediator import DataMediator


def test_a_duplicate_object_in_a_lock_set_is_caught_not_hung():
    # threading.Lock is not reentrant: acquiring the same lock twice in
    # one loop deadlocks the caller against itself, permanently and
    # silently. propose_action() already rejects an action whose
    # sub-writes resolve to the same object, so this is defence in depth
    # for any second path into the locking primitive.
    mediator = DataMediator({}, {}, {}, {})

    with pytest.raises(AssertionError, match="not reentrant"):
        with mediator._locks_for_objects([("Account", "a1"), ("Account", "a1")]):
            pass


def test_distinct_objects_in_a_lock_set_are_fine():
    # The assert must not fire on the normal case -- a multi-object
    # action legitimately locks several distinct objects at once.
    mediator = DataMediator({}, {}, {}, {})

    with mediator._locks_for_objects([("Account", "a1"), ("Account", "a2")]):
        pass


@pytest.fixture
def sync(tmp_path):
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(f"r{i}", f"v{i}") for i in range(4)])
    conn.commit()
    conn.close()
    return IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})


def test_a_transform_that_loses_rows_is_caught(sync, monkeypatch):
    # The transform stage casts values; it must never add or drop rows.
    # A silent row loss here would make the sync report success while
    # the mirror quietly holds less than the source.
    real_transform = iceberg_sync_module.transform_rows
    monkeypatch.setattr(
        iceberg_sync_module,
        "transform_rows",
        lambda rows, columns, column_types=None: real_transform(rows[:-1], columns, column_types),
    )

    with pytest.raises(AssertionError, match="transform changed the row count"):
        sync.sync_table("p", "t", "id", ["id", "v"])


def test_a_normal_sync_does_not_trip_the_row_count_assert(sync):
    result = sync.sync_table("p", "t", "id", ["id", "v"])

    assert result.row_count == 4
