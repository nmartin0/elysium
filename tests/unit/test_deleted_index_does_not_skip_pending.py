"""A delete that was pending during a sync is not lost (SEC-24).

FOUND READING core/ontology/write_log.py end to end -- a file this
agent had previously only grepped, and then counted as reviewed.

Both sync paths read `WHERE status = 'applied'` but recorded the
watermark as `MAX(rowid)` over EVERY row. A row still `pending` when a
sync ran was therefore skipped AND passed. When recovery later marked
it applied, no sync would ever look at it again: the next call
compares two integers, finds itself current, and reads nothing.

MEASURED, and the object is a deleted one:

    log: del cust_001 (pending), upd cust_999 (applied)
    sync            -> ('rebuilt', 0)   watermark = 2
    mark del applied
    sync            -> ('current', 0)   nothing read
    is_deleted      -> False
    full rebuild    -> True

`is_deleted()` reads ONLY this index, with no fallback to the log, so
the object stays readable indefinitely -- until somebody runs
`scripts/rebuild_deleted_index` by hand. Data a user deleted continues
to be served.

IT IS REACHED BY THE ORDINARY CRASH PATH, not an exotic one.
`api/app.py` syncs the index at line 354 and resumes pending writes at
line 472, so every delete left pending by a crash is skipped by the
sync that runs BEFORE the recovery that applies it. That is F-27's
scenario again, one layer further on.

ONLY `pending` BLOCKS THE WATERMARK. `abandoned` is terminal -- the
entry changed nothing and never will -- so it can be passed safely.
Treating it as blocking would stall the watermark forever behind a row
that is never coming back, and every boot would re-read the whole log.
"""

import sqlite3

import pytest

from core.ontology.write_log import WriteLogWriter

APPLIED, PENDING, ABANDONED = "applied", "pending", "abandoned"


@pytest.fixture
def log(tmp_path):
    writer = WriteLogWriter(tmp_path / "write_log.db")
    with writer._connection():
        pass  # create the schema
    return writer


def _row(log, log_id, operation, object_id, status, created_at):
    with sqlite3.connect(log.db_path) as conn:
        conn.execute(
            "INSERT INTO write_log (id, object_type, object_id, operation, changes, "
            "expected_current_values, status, user_id, description, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (log_id, "Customer", object_id, operation, "{}", "{}", status,
             "alice", "d", created_at),
        )
        conn.commit()


def _apply(log, log_id):
    with sqlite3.connect(log.db_path) as conn:
        conn.execute("UPDATE write_log SET status = 'applied' WHERE id = ?", (log_id,))
        conn.commit()


class TestADeletePendingDuringASync:
    def test_is_still_found_once_it_is_applied(self, log):
        """THE DEFECT. Before the fix the second sync said 'current'
        and read nothing, and the object stayed readable."""
        _row(log, "del-1", "delete", "cust_001", PENDING, "2026-01-01T10:00:00+00:00")
        _row(log, "upd-2", "update", "cust_999", APPLIED, "2026-01-01T10:00:01+00:00")
        log.sync_deleted_index()

        _apply(log, "del-1")
        log.sync_deleted_index()

        assert log.is_deleted("Customer", "cust_001") is True

    def test_the_incremental_path_agrees_with_a_full_rebuild(self, log):
        """The property the module already claims for itself: the
        index is a cache, and rebuilding from the log is the
        authority. A sync that disagrees with a rebuild is the bug."""
        _row(log, "del-1", "delete", "cust_001", PENDING, "2026-01-01T10:00:00+00:00")
        _row(log, "upd-2", "update", "cust_999", APPLIED, "2026-01-01T10:00:01+00:00")
        log.sync_deleted_index()
        _apply(log, "del-1")
        log.sync_deleted_index()

        incremental = log.deleted_object_ids("Customer")
        log.rebuild_deleted_index()

        assert incremental == log.deleted_object_ids("Customer")

    def test_several_pending_rows_are_all_picked_up(self, log):
        _row(log, "del-1", "delete", "cust_001", PENDING, "2026-01-01T10:00:00+00:00")
        _row(log, "del-2", "delete", "cust_002", PENDING, "2026-01-01T10:00:01+00:00")
        _row(log, "upd-3", "update", "cust_999", APPLIED, "2026-01-01T10:00:02+00:00")
        log.sync_deleted_index()

        _apply(log, "del-1")
        _apply(log, "del-2")
        log.sync_deleted_index()

        assert log.deleted_object_ids("Customer") == {"cust_001", "cust_002"}


class TestWhatMustStillWork:
    """THE OPPOSITE DIRECTION. A watermark that never advanced would
    make every boot re-read the whole log, which is the cost the
    watermark exists to avoid."""

    def test_with_nothing_pending_the_watermark_reaches_the_end(self, log):
        _row(log, "upd-1", "update", "cust_001", APPLIED, "2026-01-01T10:00:00+00:00")
        log.sync_deleted_index()

        assert log.sync_deleted_index() == ("current", 0)

    def test_an_abandoned_row_does_not_stall_it(self, log):
        """`abandoned` is terminal -- it changed nothing and never
        will. Blocking on it would stall the watermark forever."""
        _row(log, "gone-1", "update", "cust_001", ABANDONED, "2026-01-01T10:00:00+00:00")
        _row(log, "upd-2", "update", "cust_999", APPLIED, "2026-01-01T10:00:01+00:00")
        log.sync_deleted_index()

        assert log.sync_deleted_index() == ("current", 0)

    def test_a_delete_then_a_recreate_leaves_it_present(self, log):
        """The un-delete case the index already handled, pinned while
        the watermark moved underneath it."""
        _row(log, "del-1", "delete", "cust_001", APPLIED, "2026-01-01T10:00:00+00:00")
        _row(log, "new-2", "create", "cust_001", APPLIED, "2026-01-01T10:00:01+00:00")
        log.sync_deleted_index()

        assert log.is_deleted("Customer", "cust_001") is False

    def test_an_ordinary_applied_delete_still_indexes(self, log):
        _row(log, "del-1", "delete", "cust_001", APPLIED, "2026-01-01T10:00:00+00:00")
        log.sync_deleted_index()

        assert log.is_deleted("Customer", "cust_001") is True
