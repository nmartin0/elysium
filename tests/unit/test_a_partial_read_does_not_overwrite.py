"""
Half a table does not replace a whole one (PA001-F4).

THE GUARD EXISTED AND PROTECTED THE WRONG LAYER. When more than
MAX_DELETED_FRACTION of the rows vanish in one sync, the changelog
already refuses to record, and says exactly why:

    a partially-failed read looks exactly like a mass deletion and a
    changelog cannot be un-written

and then bronze and silver were overwritten with that very table.

MEASURED: a read that returned 10 of 100 rows left silver with 10,
bronze with 10, the changelog empty, and the sync reporting success.
The mirror served a tenth of the data and nothing said so. The
reasoning the changelog applied to ITSELF applies harder to silver,
which is the layer that gets SERVED -- and gold already takes this
line one layer up ("NO GOLD RATHER THAN UNAUDITED GOLD").

AN UNCHANGED MIRROR IS WRONG BY BEING STALE, which an operator can
see and fix. An overwritten one is wrong by being confident.

THE OTHER HALF OF F4 is that a REAL mass deletion must still be able
to land, or a table that genuinely emptied could never sync again.
`--accept-deletions silo.table` is that path, per-run and per-table
rather than a config key: "did half this table really just go?" has a
different answer every time it is asked.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync


@pytest.fixture
def mirror(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t VALUES (?,?)",
                     [(f"r{i}", "x") for i in range(100)])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})

    def run(**kwargs):
        return sync.sync_table("p", "t", "id", ["id", "v"], {}, **kwargs)

    def truncate_reads_to(count):
        adapter = sync.adapters["p"]
        real = adapter.read_all_rows
        adapter.read_all_rows = lambda *a, **k: real(*a, **k)[:count]

    def rows(identifier="p.t"):
        return sync.catalog.load_table(identifier).scan().to_arrow().num_rows

    def delete_all_but(keep):
        conn = sqlite3.connect(source)
        conn.execute("DELETE FROM t WHERE id NOT IN "
                     f"({','.join(repr(f'r{i}') for i in range(keep))})")
        conn.commit()
        conn.close()

    sync.run, sync.truncate_reads_to = run, truncate_reads_to
    sync.rows, sync.delete_all_but = rows, delete_all_but
    return sync


class TestTheMirrorIsLeftAlone:
    def test_a_truncated_read_is_refused(self, mirror):
        """THE REGRESSION TEST for the measurement above."""
        mirror.run()
        mirror.truncate_reads_to(10)

        with pytest.raises(ValueError, match="down from 100"):
            mirror.run()

    def test_silver_still_serves_every_row(self, mirror):
        mirror.run()
        mirror.truncate_reads_to(10)

        with pytest.raises(ValueError):
            mirror.run()

        assert mirror.rows() == 100

    def test_bronze_is_untouched_too(self, mirror):
        """Bronze is the raw record. Overwriting it with a bad read
        destroys the only copy of what the source used to say."""
        mirror.run()
        mirror.truncate_reads_to(10)

        with pytest.raises(ValueError):
            mirror.run()

        assert mirror.rows("bronze_p.t") == 100

    def test_the_message_says_what_to_do_about_it(self, mirror):
        """A refusal an operator cannot act on just becomes a habit of
        ignoring refusals."""
        mirror.run()
        mirror.truncate_reads_to(10)

        with pytest.raises(ValueError, match="--accept-deletions p.t"):
            mirror.run()


class TestARealDeletionCanStillLand:
    def test_with_the_flag_the_sync_proceeds(self, mirror):
        mirror.run()
        mirror.delete_all_but(5)

        result = mirror.run(accept_deletions=True)

        assert result.row_count == 5
        assert mirror.rows() == 5

    def test_and_the_changelog_records_it(self, mirror):
        """The deletions become history, which is the point of saying
        yes rather than working around the guard."""
        mirror.run()
        mirror.delete_all_but(5)

        mirror.run(accept_deletions=True)

        changes = mirror.catalog.load_table("changelog_p.t").scan().to_arrow().to_pylist()
        assert sum(1 for row in changes if row["_change"] == "DELETE") == 95


class TestOrdinarySyncsAreUnaffected:
    def test_a_small_deletion_needs_no_flag(self, mirror):
        """Below the threshold is the overwhelmingly common case and
        must not become a support question."""
        mirror.run()
        mirror.delete_all_but(60)

        assert mirror.run().row_count == 60

    def test_exactly_at_the_threshold_is_allowed(self, mirror):
        """50 of 100 is the boundary. The guard fires above the
        fraction, not at it -- pinned so a later tweak has to be
        deliberate."""
        mirror.run()
        mirror.delete_all_but(50)

        assert mirror.run().row_count == 50

    def test_a_growing_table_is_never_refused(self, mirror):
        mirror.run()
        conn = sqlite3.connect(mirror.adapters["p"].db_path)
        conn.executemany("INSERT INTO t VALUES (?,?)",
                         [(f"n{i}", "y") for i in range(50)])
        conn.commit()
        conn.close()

        assert mirror.run().row_count == 150

    def test_a_first_sync_has_nothing_to_compare(self, mirror):
        """No previous table means no fraction, and a new deployment
        must not be refused for having fewer rows than nothing."""
        assert mirror.run().row_count == 100
