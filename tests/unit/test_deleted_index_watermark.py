"""
Keeping the deleted-object index current (F-28).

THE QUESTION WAS "rebuild at startup, or by an operator script", and
the audit recommended the script "given the scan's cost". MEASURING
THAT COST CHANGED THE ANSWER: a rebuild is one pass over the log --
22 ms per 10,000 rows, 206 ms per 100,000, 1.07 s per 500,000, linear
and growing forever because the log is append-only.

AND ANY CHECK IS ALSO ONE PASS. Detecting staleness by comparing the
index with what the log implies costs what the rebuild costs, so
detection could never be much cheaper than the thing it was meant to
avoid. That is what rules out the middle option.

A WATERMARK ESCAPES BOTH. The index remembers the highest log row it
has consumed; a boot compares two integers. Measured on a 50,000-row
log: 80.9 ms to rebuild the first time, 0.39 ms to find it current the
second, 1.25 ms to catch up after one write.

THE SCRIPT STILL EXISTS, for the case a watermark cannot cover: an
index that is WRONG rather than behind -- a restore, a manual edit, a
write-path bug since fixed. The watermark says what the index has
SEEN, not that its contents are right.
"""

import random
import sqlite3

import pytest

from core.ontology.write_log import WriteLogWriter


def _append(database, entries):
    """Write log rows directly, as the write path would."""
    conn = sqlite3.connect(database)
    conn.executemany(
        "INSERT INTO write_log (id, object_type, object_id, operation, changes, "
        "expected_current_values, status, user_id, description, created_at) "
        "VALUES (?,?,?,?,'{}','{}',?,'u','d',?)",
        entries,
    )
    conn.commit()
    conn.close()


def _deleted(log):
    conn = sqlite3.connect(log.db_path)
    rows = conn.execute("SELECT object_type, object_id FROM object_deleted").fetchall()
    conn.close()
    return sorted(rows)


@pytest.fixture
def log(tmp_path):
    written = WriteLogWriter(tmp_path / "write_log.db")
    with written._connection():
        pass  # creates the schema
    return written


class TestTheThreeOutcomes:
    def test_a_log_never_synced_is_rebuilt(self, log):
        _append(log.db_path, [("w1", "Customer", "c1", "delete", "applied", "2026-01-01")])

        outcome, _ = log.sync_deleted_index()

        assert outcome == "rebuilt"
        assert _deleted(log) == [("Customer", "c1")]

    def test_a_second_boot_finds_it_current(self, log):
        _append(log.db_path, [("w1", "Customer", "c1", "delete", "applied", "2026-01-01")])
        log.sync_deleted_index()

        outcome, rows = log.sync_deleted_index()

        assert outcome == "current" and rows == 0

    def test_new_rows_are_caught_up_without_reading_the_rest(self, log):
        _append(log.db_path, [(f"w{i}", "Customer", f"c{i}", "update", "applied",
                                "2026-01-01") for i in range(100)])
        log.sync_deleted_index()

        _append(log.db_path, [("late", "Customer", "c7", "delete", "applied", "2026-01-02")])
        outcome, rows = log.sync_deleted_index()

        assert outcome == "caught-up"
        assert rows == 1, "only the new row was read"
        assert ("Customer", "c7") in _deleted(log)

    def test_an_empty_log_is_not_an_error(self, log):
        outcome, rows = log.sync_deleted_index()

        assert outcome == "rebuilt" and rows == 0


class TestIncrementalAgreesWithAFullRebuild:
    """THE PROPERTY THE WHOLE DESIGN RESTS ON, asserted rather than
    argued: applying new rows in order gives the same index as
    resolving latest-per-object over the whole log."""

    def test_on_a_randomised_workload(self, log):
        random.seed(20260924)
        operations = ("create", "update", "delete")
        entries = []
        for i in range(400):
            entries.append((
                f"w{i}",
                random.choice(("Customer", "Transaction")),
                f"o{random.randint(1, 40)}",
                random.choice(operations),
                random.choice(("applied", "applied", "applied", "pending")),
                f"2026-01-{(i % 28) + 1:02d}T00:00:{i % 60:02d}",
            ))
        # Synced in several chunks, the way a running service would.
        for start in range(0, len(entries), 37):
            _append(log.db_path, entries[start:start + 37])
            log.sync_deleted_index()
        incremental = _deleted(log)

        log.rebuild_deleted_index()

        assert incremental == _deleted(log)

    def test_a_row_arriving_OUT_OF_ORDER_falls_back_to_a_rebuild(self, log):
        """THE ASSUMPTION THE INCREMENTAL PATH RESTS ON, and what
        happens when it breaks.

        A full rebuild resolves latest-per-object by (created_at, id);
        applying new rows in ARRIVAL order agrees only while created_at
        increases with arrival. It does, because the write path stamps
        it as it writes -- but a backfill, a clock stepping backwards
        or an imported log would break it silently, and the index would
        then disagree with the log in the direction that HIDES AN
        OBJECT THAT EXISTS.

        FOUND BY THE RANDOMISED TEST ABOVE, which generated
        out-of-order timestamps and caught the two paths disagreeing.
        """
        _append(log.db_path, [("w1", "Customer", "c1", "delete", "applied", "2026-06-01")])
        log.sync_deleted_index()

        # Arrives later, but is STAMPED earlier -- so by the log's own
        # ordering the delete is still the latest word on c1.
        _append(log.db_path, [("w2", "Customer", "c1", "create", "applied", "2026-01-01")])
        outcome, _ = log.sync_deleted_index()

        assert outcome == "rebuilt"
        assert _deleted(log) == [("Customer", "c1")], \
            "the delete is later BY THE LOG'S ORDERING, so c1 stays deleted"

    def test_a_delete_followed_by_a_create_un_deletes(self, log):
        """The case a naive "only add deletes" index gets wrong -- and
        gets wrong in the DANGEROUS direction, hiding an object that
        exists."""
        _append(log.db_path, [("w1", "Customer", "c1", "delete", "applied", "2026-01-01")])
        log.sync_deleted_index()

        _append(log.db_path, [("w2", "Customer", "c1", "create", "applied", "2026-01-02")])
        log.sync_deleted_index()

        assert _deleted(log) == []

    def test_a_pending_write_does_not_reach_the_index_on_a_REBUILD(self, log):
        _append(log.db_path, [("w1", "Customer", "c1", "delete", "pending", "2026-01-01")])

        log.sync_deleted_index()

        assert _deleted(log) == []

    def test_nor_on_the_INCREMENTAL_path(self, log):
        """WRITTEN BECAUSE A CONTROL PROVED NOTHING: the test above
        starts with no watermark, so it takes the rebuild path and
        never exercises the incremental filter. A pending write that
        arrives AFTER a sync is the case that does -- and a pending
        delete reaching the index would hide an object over a write
        nobody has approved yet."""
        _append(log.db_path, [("w1", "Customer", "c1", "update", "applied", "2026-01-01")])
        log.sync_deleted_index()

        _append(log.db_path, [("w2", "Customer", "c1", "delete", "pending", "2026-01-02")])
        outcome, _ = log.sync_deleted_index()

        assert outcome == "caught-up"
        assert _deleted(log) == []


class TestTheWatermark:
    def test_a_rebuild_leaves_one_behind(self, log):
        """So the boot after a manual rebuild is free rather than
        another rebuild."""
        _append(log.db_path, [("w1", "Customer", "c1", "delete", "applied", "2026-01-01")])

        log.rebuild_deleted_index()

        assert log.sync_deleted_index() == ("current", 0)

    def test_losing_it_forces_a_rebuild_rather_than_silence(self, log):
        """A restored backup without the meta table must not be
        mistaken for an index that is up to date."""
        _append(log.db_path, [("w1", "Customer", "c1", "delete", "applied", "2026-01-01")])
        log.sync_deleted_index()
        conn = sqlite3.connect(log.db_path)
        conn.execute("DELETE FROM write_log_meta")
        conn.commit()
        conn.close()

        outcome, _ = log.sync_deleted_index()

        assert outcome == "rebuilt"


class TestTheOperatorScript:
    def test_it_rebuilds_and_reports(self, log, capsys):
        from scripts.rebuild_deleted_index import rebuild

        _append(log.db_path, [("w1", "Customer", "c1", "delete", "applied", "2026-01-01")])

        assert rebuild(log.db_path.parent) == 0

        printed = capsys.readouterr().out
        assert "1 object(s) marked deleted" in printed
        assert _deleted(log) == [("Customer", "c1")]

    def test_it_says_so_when_there_is_no_log(self, tmp_path, capsys):
        from scripts.rebuild_deleted_index import rebuild

        assert rebuild(tmp_path) == 1
        assert "no write log" in capsys.readouterr().err
