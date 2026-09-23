"""
The mirror serves reads from whole tables cached by snapshot -- and
returns exactly what a direct scan would (E-10).

MEASURED, same machine, back to back: search_object from the mirror
15.31 ms before, 0.99 ms after (live: 1.35); get_field 11.82 -> 2.51
(live: 1.46). Speed is only worth having if the answers are identical,
so most of this file is PARITY: the cached path against the direct
scan, filter by filter.
"""

import contextlib
import io
import sqlite3

import pytest
from pyiceberg.expressions import And, EqualTo, In, NotEqualTo, NotIn

import core.mirror.iceberg_reader as reader_module
import core.mirror.mirror_adapter as mirror_module
from core.mirror.snapshot_cache import SnapshotCache
from scripts.run_sync import run_sync


def _pinned_adapter(paths):
    """A mirror adapter over a deployment's lake, pinned to its current
    snapshots -- exactly as core/deployment_loader.py pins them."""
    from pyiceberg.catalog.sql import SqlCatalog

    from core.mirror.mirror_adapter import MirrorReadAdapter

    mirror_dir = paths.data_dir / "mirror"
    catalog = SqlCatalog(
        "elysium_mirror",
        uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
        warehouse=f"file://{mirror_dir / 'warehouse'}",
    )
    pinned = {}
    for identifier in catalog.list_tables("primary_sql"):
        snapshot = catalog.load_table(identifier).current_snapshot()
        if snapshot is not None:
            pinned[identifier[-1]] = snapshot.snapshot_id
    return MirrorReadAdapter(catalog, "primary_sql", snapshot_ids=pinned)


@pytest.fixture
def mirror(synced_deployment):
    """The mirror adapter itself, built over the deployment's lake.

    IT USED TO COME FROM THE READ MEDIATOR, which no longer holds one:
    reads are served by the gold connector alone (GOLD-8), and keeping
    the source adapters there "just in case" is how a fallback comes
    back. What this file tests is the ADAPTER's cache, so it builds
    one.
    """
    return _pinned_adapter(synced_deployment), synced_deployment


def _direct(adapter, table_name, selected, row_filter=None, limit=None):
    """What a scan returns with no cache at all."""
    table = adapter._catalog.load_table(f"{adapter.silo_name}.{table_name}")
    kwargs = {"selected_fields": selected, "snapshot_id": adapter._reader._snapshot_ids.get(table_name)}
    if row_filter is not None:
        kwargs["row_filter"] = row_filter
    if limit:
        kwargs["limit"] = limit
    return table.scan(**{k: v for k, v in kwargs.items() if v is not None}).to_arrow()


FILTERS = [
    None,
    EqualTo("region", "us-west"),
    In("region", ["us-west", "us-east"]),
    NotIn("region", ["us-east"]),
    NotEqualTo("region", "us-west"),
    And(EqualTo("region", "us-west"), NotEqualTo("customer_id", "cust_001")),
]


class TestParity:
    @pytest.mark.parametrize("row_filter", FILTERS, ids=lambda f: type(f).__name__ if f else "none")
    def test_each_filter_returns_what_a_scan_returns(self, mirror, row_filter):
        adapter, _ = mirror
        selected = ("customer_id", "name", "region")

        cached = adapter._reader._scan("customers", selected, row_filter=row_filter)

        assert cached.to_pylist() == _direct(adapter, "customers", selected, row_filter).to_pylist()

    def test_columns_come_in_the_tables_order_as_a_scan_gives_them(self, mirror):
        adapter, _ = mirror
        asked = ("region", "customer_id")

        cached = adapter._reader._scan("customers", asked)

        assert cached.column_names == _direct(adapter, "customers", asked).column_names

    def test_a_limit_takes_the_same_rows(self, mirror):
        adapter, _ = mirror
        selected = ("customer_id",)

        cached = adapter._reader._scan("customers", selected, limit=2)

        assert cached.to_pylist() == _direct(adapter, "customers", selected, limit=2).to_pylist()


class TestWhatTheCacheSaves:
    def test_a_cached_pinned_table_needs_no_catalog(self, mirror, monkeypatch):
        adapter, _ = mirror
        adapter._reader._scan("customers", ("customer_id",))

        def gone(*args, **kwargs):
            raise AssertionError("the catalog was consulted")
        monkeypatch.setattr(adapter._catalog, "load_table", gone)

        assert adapter._reader._scan("customers", ("customer_id",)).num_rows > 0

    def test_a_large_table_is_never_read_whole(self, mirror, monkeypatch):
        """Judged from the snapshot summary BEFORE reading, so a limit
        pushed into the direct scan keeps meaning what it says."""
        adapter, _ = mirror
        monkeypatch.setattr(reader_module, "MAX_CACHED_ROWS", 1)

        rows = adapter._reader._scan("customers", ("customer_id",), limit=1)

        assert rows.num_rows == 1
        assert adapter._reader._snapshot_cache.get((
            "customers", adapter._reader._snapshot_ids["customers"])) is None


class TestNeverStale:
    def test_a_pinned_generation_keeps_its_snapshot_and_a_new_one_sees_the_sync(self, mirror):
        """KEYED BY SNAPSHOT: a sync writes a new snapshot, so a new key;
        nothing is ever invalidated, and nothing can be stale."""
        old_adapter, paths = mirror
        before = old_adapter._reader._scan("customers", ("customer_id", "name"), EqualTo("customer_id", "cust_001"))

        with sqlite3.connect(paths.data_dir / "dev_fixtures" / "mediator.db") as conn:
            conn.execute("UPDATE customers SET name = 'Renamed' WHERE customer_id = 'cust_001'")
        with contextlib.redirect_stdout(io.StringIO()):
            assert run_sync(paths) == 0
        # A SECOND ADAPTER over the same lake, pinned to what the sync
        # just published -- which is what a new generation used to hand
        # back before reads moved to gold (GOLD-8).
        new_adapter = _pinned_adapter(paths)

        again = old_adapter._reader._scan("customers", ("customer_id", "name"), EqualTo("customer_id", "cust_001"))
        fresh = new_adapter._reader._scan("customers", ("customer_id", "name"), EqualTo("customer_id", "cust_001"))
        assert again.to_pylist() == before.to_pylist()
        assert fresh.to_pylist() == [{"customer_id": "cust_001", "name": "Renamed"}]


    def test_one_unpinned_adapter_sees_a_sync_at_once(self, mirror):
        """WHERE THE SNAPSHOT IN THE KEY MATTERS. The test above uses two
        adapters, each with its own cache, and would pass with a key of
        the table alone. One adapter with no pin -- a table first synced
        after its generation was built -- reads the CURRENT snapshot, so
        the same instance must not answer from the old one."""
        pinned, paths = mirror
        unpinned = mirror_module.MirrorReadAdapter(pinned._catalog, pinned.silo_name, snapshot_ids=None)
        unpinned._reader._scan("customers", ("customer_id", "name"), EqualTo("customer_id", "cust_001"))

        with sqlite3.connect(paths.data_dir / "dev_fixtures" / "mediator.db") as conn:
            conn.execute("UPDATE customers SET name = 'Renamed' WHERE customer_id = 'cust_001'")
        with contextlib.redirect_stdout(io.StringIO()):
            assert run_sync(paths) == 0

        after = unpinned._reader._scan("customers", ("customer_id", "name"), EqualTo("customer_id", "cust_001"))
        assert after.to_pylist() == [{"customer_id": "cust_001", "name": "Renamed"}]

class TestTheCache:
    def test_evicts_the_least_recently_used_to_stay_in_budget(self):
        cache = SnapshotCache(max_bytes=10)
        cache.put("a", "A", 4)
        cache.put("b", "B", 4)
        cache.get("a")          # a is now the more recent
        cache.put("c", "C", 4)  # b goes

        assert (cache.get("a"), cache.get("b"), cache.get("c")) == ("A", None, "C")

    def test_refuses_one_larger_than_the_whole_budget(self):
        cache = SnapshotCache(max_bytes=10)
        cache.put("a", "A", 4)

        assert cache.put("huge", "H", 11) is False
        assert cache.get("a") == "A"  # nothing evicted for it
