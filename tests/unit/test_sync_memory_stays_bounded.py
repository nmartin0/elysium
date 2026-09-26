"""
What a sync costs in memory, measured and bounded (PA001-A14).

THE FINDING: "~2.6 KB/row peak, about ten whole-table
materialisations per sync", measured by the audit at 342 MB for 50,000
rows on a598ed0.

MEASURED HERE, on current code:

    50,000 rows x 1 column    1,727 B/row
    50,000 rows x 3 columns   1,595 B/row
    50,000 rows x 8 columns   2,906 B/row

    peak against the raw data:  17.3x (3 columns), 8.9x (8 columns)

So the finding holds. Around two kilobytes per row, near enough
unchanged, and a peak that is roughly ten times the bytes being
copied.

TWO THINGS THE MEASUREMENT ADDS.

NOTHING LEAKS. After a sync, the largest live allocations are Python
imports; none of the row data survives. The cost is a transient peak,
which is the difference between "a big table needs a big machine" and
"a long-running server grows until it dies".

THE COST IS PER ROW, NOT PER BYTE. Widening a table from 1 column to 8
-- eight times the data -- less than doubles the per-row figure. What
dominates is the Python object overhead of materialising every row as
a dict of strs, not the number of copies of the payload. That matters
because it tells you which fix works: batching (PR001-R5) or
streaming, not "make fewer copies".

WHY THIS IS A GUARD AND NOT A FIX. Bounding it properly means the sync
reading and writing in batches rather than whole tables -- PR001-R5, a
design change with its own consequences for the changelog diff and the
partial-read guard, both of which currently compare WHOLE tables. That
is not a patch. This test stops it getting quietly worse in the
meantime.

WHAT THIS TEST CAN AND CANNOT DETECT, measured rather than assumed,
because the first version of this docstring claimed more than it
delivers.

I added deliberate extra materialisations of every row and watched the
per-row figure:

    0 extra copies   2,572 B/row
    3 extra copies   1,745 B/row     <- LOWER than zero
    6 extra copies   2,323 B/row
   12 extra copies   3,479 B/row

The measurement swings by about 40% between runs, so THREE EXTRA FULL
COPIES OF EVERY ROW ARE INVISIBLE TO IT. The bound catches a
catastrophe -- something materialising the table many times over --
and nothing subtler. That is worth having and it is not a memory
budget.

The leak check below is the reliable one: whether row data is still
allocated after the sync returns is a yes-or-no question, and noise
does not change the answer.
"""

import sqlite3
import tracemalloc

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

ROWS = 20_000
# Roughly double what is measured today (~2-3 KB/row). Catches a
# regression that doubles the cost; ignores the noise between runs.
MAX_BYTES_PER_ROW = 6_000


def _sync_peak(tmp_path, rows: int, width: int) -> int:
    source = tmp_path / f"s{width}.db"
    columns = [f"c{i}" for i in range(width)]
    conn = sqlite3.connect(source)
    conn.execute(f"CREATE TABLE t (id TEXT PRIMARY KEY, "
                 f"{', '.join(f'{c} TEXT' for c in columns)})")
    conn.executemany(
        f"INSERT INTO t VALUES ({','.join('?' * (width + 1))})",
        [(f"r{i}", *["x" * 40] * width) for i in range(rows)])
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / f"m{width}",
                              {"p": SQLiteReadAdapter({"path": source})})

    tracemalloc.start()
    try:
        sync.sync_table("p", "t", "id", ["id", *columns], {})
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


class TestTheCostPerRow:
    @pytest.mark.parametrize("width", [1, 4])
    def test_it_stays_under_the_bound(self, tmp_path, width):
        peak = _sync_peak(tmp_path, ROWS, width)

        per_row = peak / ROWS
        assert per_row < MAX_BYTES_PER_ROW, (
            f"a sync now costs {per_row:.0f} B/row at {width} column(s), "
            f"over the {MAX_BYTES_PER_ROW} B/row bound. Either something "
            f"started materialising the table again, or the bound needs "
            f"raising deliberately -- do not raise it to make this pass.")

    def test_four_times_the_data_is_not_four_times_the_peak(self, tmp_path):
        """The finding that tells you which fix works: the cost is
        dominated by per-ROW Python objects, not by copies of the
        payload.

        The factor of three here is loose for the same reason as the
        bound above -- these measurements swing by around 40% -- so
        this catches a change in KIND (cost becoming proportional to
        the bytes) rather than a change in degree."""
        narrow = _sync_peak(tmp_path, ROWS, 1)
        wide = _sync_peak(tmp_path, ROWS, 4)

        assert wide < narrow * 3, (
            f"{narrow/1e6:.1f} MB -> {wide/1e6:.1f} MB for 4x the data: the "
            f"cost has become proportional to the payload, which would mean "
            f"whole-table copies dominate after all")


class TestNothingSurvivesTheSync:
    def test_the_rows_are_released(self, tmp_path):
        """A transient peak is survivable; a leak is not. This is the
        difference between "a big table needs a big machine" and "a
        long-running server grows until it dies"."""
        source = tmp_path / "leak.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
        conn.executemany("INSERT INTO t VALUES (?,?)",
                         [(f"r{i}", "x" * 200) for i in range(ROWS)])
        conn.commit()
        conn.close()
        sync = IcebergMirrorSync(tmp_path / "lm",
                                  {"p": SQLiteReadAdapter({"path": source})})

        tracemalloc.start()
        try:
            sync.sync_table("p", "t", "id", ["id", "v"], {})
            still_held, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        payload = ROWS * 200
        assert still_held < payload, (
            f"{still_held/1e6:.1f} MB still allocated after the sync, against "
            f"{payload/1e6:.1f} MB of row data -- the rows are being held")
