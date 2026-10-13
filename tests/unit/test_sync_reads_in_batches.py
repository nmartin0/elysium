"""
A sync reads, stores and cleans a table a batch at a time (R5).

THE COST IT REMOVES, measured on 200,000 rows x 4 columns (peak RSS):

    first sync              700 MB  ->  463 MB
    re-sync, one row changed 827 MB  ->  510-590 MB (varies by run)

The rows used to exist as Python dicts three times over -- read from
the source, read back from bronze, and both snapshots in the changelog
diff. Now the source is streamed into bronze as Arrow, bronze is read
back as Arrow and cleaned a batch at a time, and the diff compares
columns and builds dicts only for rows that changed.

WHAT STILL HOLDS THE WHOLE TABLE, so nobody reads "bounded" as more
than it is: the CLEANED rows (silver is written in one transaction,
which is what makes a failed sync leave the old table intact), and the
Arrow tables themselves -- compact, but whole. The peak is lower by a
constant factor; it still grows with the table.

THE PROMISE THESE TESTS HOLD: batching changes the cost and NOTHING
ELSE. A sync at a batch size of 7 must leave the same silver, bronze,
quarantine and changelog as a sync that read everything at once.
"""

import sqlite3

import pytest

import core.mirror.iceberg_sync as iceberg_sync
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.transform import transform_batches, transform_rows
from core.ontology.interface import ExternalReadAdapter, StorageUnavailable

COLUMNS = ["id", "n", "region"]
TYPES = {"id": "string", "n": "integer", "region": "string"}
ROWS = 50


def _source(path, rows):
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, n TEXT, region TEXT, extra TEXT)")
    connection.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
    connection.commit()
    connection.close()


def _rows():
    # TWO BAD CELLS IN DIFFERENT BATCHES at a batch size of 7 -- rows 3
    # and 40 -- so the merge of drift and row indices across batches is
    # what decides the quarantine.
    return [(f"r{i:03}", "N/A" if i in (3, 40) else str(i), f"us-{i % 3}", "x")
            for i in range(ROWS)]


def _tables(sync, *identifiers):
    out = {}
    for identifier in identifiers:
        try:
            table = sync._catalog.load_table(identifier).scan().to_arrow()
        except Exception:  # noqa: BLE001 - absent is an answer here
            out[identifier] = None
            continue
        # WHEN, not WHAT: timestamps of the run itself differ between two runs.
        clock = [c for c in table.column_names if c.startswith("_") or c == "detected_at"]
        rows = table.drop(clock).to_pylist()
        out[identifier] = sorted(rows, key=repr)
    return out


def _sync_twice(tmp_path, batch_size, monkeypatch):
    monkeypatch.setattr(iceberg_sync, "SYNC_BATCH_ROWS", batch_size)
    source = tmp_path / f"s{batch_size}.db"
    _source(source, _rows())
    sync = IcebergMirrorSync(tmp_path / f"m{batch_size}", {"s": SQLiteReadAdapter({"path": source})},
                              on_type_mismatch="quarantine")
    first = sync.sync_table("s", "t", "id", COLUMNS, TYPES)
    connection = sqlite3.connect(source)
    connection.execute("UPDATE t SET region = 'eu' WHERE id IN ('r001', 'r030')")
    connection.execute("DELETE FROM t WHERE id = 'r045'")
    connection.execute("INSERT INTO t VALUES ('r999', '7', 'ap', 'x')")
    connection.commit()
    connection.close()
    second = sync.sync_table("s", "t", "id", COLUMNS, TYPES)
    return sync, first, second


class TestBatchingChangesNothingButTheCost:
    def test_every_table_is_the_same_at_any_batch_size(self, tmp_path, monkeypatch):
        small, small_first, small_second = _sync_twice(tmp_path, 7, monkeypatch)
        whole, whole_first, whole_second = _sync_twice(tmp_path, 1_000_000, monkeypatch)

        names = ("s.t", "bronze_s.t", "quarantine_s.t", "changelog_s.t")
        batched, unbatched = _tables(small, *names), _tables(whole, *names)
        for name in names:
            assert batched[name] == unbatched[name], name
        # And the tables were really exercised, not all empty.
        assert len(batched["s.t"]) == ROWS - 2
        assert len(batched["quarantine_s.t"]) >= 2
        assert {row["_change"] for row in _changelog(small)} >= {"INSERT", "UPDATE", "DELETE"}
        assert small_first.row_count == whole_first.row_count
        assert small_second.row_count == whole_second.row_count

    def test_no_batch_larger_than_the_bound_reaches_the_clean_step(self, tmp_path, monkeypatch):
        seen = []

        def recording(rows, *args, **kwargs):
            seen.append(len(rows))
            return transform_rows(rows, *args, **kwargs)

        monkeypatch.setattr("core.mirror.transform.transform_rows", recording)
        _sync_twice(tmp_path, 7, monkeypatch)

        assert seen and max(seen) <= 7
        assert sum(seen) >= ROWS  # every row was cleaned, once per sync

    def test_the_normal_path_never_asks_for_the_whole_table(self, tmp_path, monkeypatch):
        """read_all_rows is the whole table as dicts at once. A sync
        whose bronze is current reads through iter_all_rows only."""
        def refuse(*_args, **_kwargs):
            raise AssertionError("read_all_rows called on the normal path")

        monkeypatch.setattr(SQLiteReadAdapter, "read_all_rows", refuse)
        _sync_twice(tmp_path, 7, monkeypatch)


def _changelog(sync):
    return sync._catalog.load_table("changelog_s.t").scan().to_arrow().to_pylist()


class TestTheAdapterBatches:
    @pytest.fixture
    def adapter(self, tmp_path):
        source = tmp_path / "a.db"
        _source(source, _rows())
        return SQLiteReadAdapter({"path": source})

    def test_sqlite_yields_the_same_rows_in_bounded_pieces(self, adapter):
        config = {"storage": {"table": "t", "id_column": "id"}}
        batches = list(adapter.iter_all_rows("t", COLUMNS, config, batch_size=7))

        assert [len(batch) for batch in batches] == [7] * 7 + [1]
        assert [row for batch in batches for row in batch] == adapter.read_all_rows("t", COLUMNS, config)

    def test_a_missing_table_is_unavailable_not_empty(self, adapter):
        with pytest.raises(StorageUnavailable):
            list(adapter.iter_all_rows("nope", COLUMNS, {}, batch_size=7))

    def test_no_columns_reads_nothing(self, adapter):
        assert list(adapter.iter_all_rows("t", [], {}, batch_size=7)) == []

    def test_an_adapter_that_cannot_stream_still_works(self):
        """The interface's default: correct for any adapter, by slicing
        read_all_rows. No better on memory, and says so."""
        from types import SimpleNamespace

        plain = SimpleNamespace(read_all_rows=lambda *_: [{"id": str(i)} for i in range(10)])
        batches = list(ExternalReadAdapter.iter_all_rows(plain, "t", ["id"], {}, batch_size=4))

        assert [len(batch) for batch in batches] == [4, 4, 2]


class TestTransformBatchesIsTransformRows:
    def test_the_merged_result_is_the_unbatched_one(self):
        rows = [{"id": f"r{i}", "n": f"bad{i}" if i % 11 == 4 else str(i),
                 "d": "never" if i == 30 else "2026-01-02"} for i in range(60)]
        types = {"id": "string", "n": "integer", "d": "date"}
        whole = transform_rows(rows, ["id", "n", "d"], types)

        for size in (1, 7, 59, 60, 1000):
            batched = transform_batches((rows[i:i + size] for i in range(0, len(rows), size)),
                                        ["id", "n", "d"], types)
            assert batched.rows == whole.rows, size
            assert batched.drift == whole.drift, size
            assert batched.mismatched_row_indices == whole.mismatched_row_indices, size
            assert batched.mismatched_cells == whole.mismatched_cells, size

    def test_no_batches_is_an_empty_table(self):
        result = transform_batches(iter([]), ["id"], {})
        assert result.rows == [] and result.drift == [] and not result.has_drift


class _Batch(list):
    """A list that can be weakly referenced, so a test can ask whether
    the sync still holds it."""


def test_the_source_rows_are_not_kept_while_the_next_batch_is_read(tmp_path, monkeypatch):
    """THE BRONZE WRITE STREAMS: by the time the source hands over a
    batch, the dicts of the batch before last are gone. A sync that
    gathered the rows into one list -- the old pa.Table.from_pylist
    over everything -- keeps every one of them alive and fails this."""
    import gc
    import weakref

    original = SQLiteReadAdapter.iter_all_rows
    still_alive = []

    def watched(self, *args, **kwargs):
        earlier = []
        for batch in original(self, *args, **kwargs):
            gc.collect()
            still_alive.extend(ref for ref in earlier[:-1] if ref() is not None)
            batch = _Batch(batch)
            earlier.append(weakref.ref(batch))
            yield batch
            del batch

    monkeypatch.setattr(SQLiteReadAdapter, "iter_all_rows", watched)
    _sync_twice(tmp_path, 7, monkeypatch)

    assert still_alive == [], f"{len(still_alive)} source batch(es) still held by the sync"
