"""
Old-generation adapters keep working while new ones are built.

STEP 5f OF HOT_RELOAD_PLAN.md, which said refcounting retires old
adapters for free IF they hold no process-global state -- and said to
VERIFY that rather than assume it. sqlite_adapter had been checked; the
mirror adapter's catalog handle had not.

THE RISK IS SPECIFIC. A reload builds a whole new generation, including
a second SqlCatalog over the SAME catalog.db, while requests pinned to
the previous generation are still reading through the first. If two
catalogs over one SQLite file interfered, a reload would break every
in-flight query -- and it would do so under concurrency, which is the
hardest kind of failure to reproduce from a bug report.

Written as a test rather than left as a probe, because the property
belongs to pyiceberg and SQLite rather than to us: a dependency bump
could take it away, and nothing else here would notice.
"""

import sqlite3
import threading

import pytest
from pyiceberg.catalog.sql import SqlCatalog

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter

ROWS = 200


@pytest.fixture
def mirrored(tmp_path):
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?)",
        [(f"c{i}", f"name{i}") for i in range(ROWS)],
    )
    conn.commit()
    conn.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})})
    sync.sync_table("primary", "customers", "customer_id", ["customer_id", "name"],
                    {"customer_id": "string", "name": "string"})
    return tmp_path / "mirror"


def _catalog(mirror_dir):
    # A fresh catalog per call, which is what build_generation() does --
    # one shared across the silos of ONE generation, never reused
    # across two.
    return SqlCatalog(
        "elysium_mirror",
        uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
        warehouse=f"file://{mirror_dir / 'warehouse'}",
    )


def test_two_generations_can_hold_catalogs_over_one_mirror(mirrored):
    old = MirrorReadAdapter(_catalog(mirrored), "primary")
    new = MirrorReadAdapter(_catalog(mirrored), "primary")

    assert old._scan("customers", ("customer_id", "name")).num_rows == ROWS
    assert new._scan("customers", ("customer_id", "name")).num_rows == ROWS


def test_an_in_flight_read_survives_a_generation_being_built_beneath_it(mirrored):
    # THE PROPERTY 5f ACTUALLY NEEDS, and the one that only shows up
    # under concurrency: a request pinned to the old generation keeps
    # reading correctly while a reload constructs the next one.
    old = MirrorReadAdapter(_catalog(mirrored), "primary")
    failures = []

    def keep_reading():
        try:
            for _ in range(20):
                assert old._scan("customers", ("customer_id", "name")).num_rows == ROWS
        except Exception as error:  # noqa: BLE001 -- reported, not swallowed
            failures.append(repr(error))

    reader = threading.Thread(target=keep_reading)
    reader.start()
    try:
        for _ in range(10):
            MirrorReadAdapter(_catalog(mirrored), "primary")._scan(
                "customers", ("customer_id", "name")
            )
    finally:
        reader.join(timeout=60)

    assert not reader.is_alive(), "the in-flight reader never finished"
    assert failures == [], f"reads on the old generation failed during a reload: {failures}"


def test_the_adapters_hold_no_module_level_state(mirrored):
    # WHY REFCOUNTING IS ENOUGH. An old generation is freed when the
    # last request pinning it finishes -- which only works if nothing
    # outside that generation holds a reference. Module-level caches,
    # class attributes and lru_caches are all ways for one to survive,
    # and a survivor would serve a configuration nobody is running.
    import adapters.sqlite_adapter as sqlite_module
    import core.mirror.mirror_adapter as mirror_module

    for module in (sqlite_module, mirror_module):
        cached = [
            name for name in dir(module)
            if hasattr(getattr(module, name), "cache_clear")
        ]
        assert cached == [], f"{module.__name__} memoises at module level: {cached}"

    # And no adapter INSTANCE state is shared between two of them.
    first = MirrorReadAdapter(_catalog(mirrored), "primary")
    second = MirrorReadAdapter(_catalog(mirrored), "primary")

    assert first._catalog is not second._catalog
