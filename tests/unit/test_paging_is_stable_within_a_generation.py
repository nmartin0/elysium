"""
Paging a mirror deployment does not see rows change underneath it.

UI_ROADMAP.md records: "Paging consistency is documented, not
guaranteed. Default paging returns the latest results and may duplicate
or miss rows if data changes between pages. Fine for browsing, wrong
for an export."

THAT NOTE PREDATES SNAPSHOT PINNING and is now too weak for a mirror
deployment. A generation records the Iceberg snapshot id of each table
when it is built, and every read in that generation uses it -- so page
one and page two of the same query read the same immutable snapshot
even if a sync commits between them.

It remains exactly right for a LIVE deployment, which reads the
customer's database directly and has no snapshot to pin.

Tested rather than reasoned about, because the guarantee is worth
nothing if a future change quietly drops the pin.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter

TYPE_CONFIG = {"storage": {"table": "customers", "id_column": "customer_id"}}
COLUMNS = ["customer_id", "name"]
TYPES = {"customer_id": "string", "name": "string"}


@pytest.fixture
def mirrored(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    connection.executemany(
        "INSERT INTO customers VALUES (?, ?)",
        [(f"c{n}", f"name{n}") for n in range(5)],
    )
    connection.commit()
    connection.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})})
    sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES)
    return sync, source


def _snapshot_of(sync):
    table = sync._catalog.load_table("primary.customers")
    return {"customers": table.current_snapshot().snapshot_id}


def _rows(sync, pinned):
    adapter = MirrorReadAdapter(sync._catalog, "primary", snapshot_ids=pinned)
    return adapter.read_all_rows("customers", COLUMNS, TYPE_CONFIG)


def test_a_pinned_read_does_not_see_a_later_sync(mirrored):
    """THE PROPERTY. Page one and page two read the same snapshot.

    Simulated with two reads either side of a sync, which is what
    paging actually is: separate requests against one generation.
    """
    sync, source = mirrored
    pinned = _snapshot_of(sync)
    before = _rows(sync, pinned)

    connection = sqlite3.connect(source)
    connection.execute("INSERT INTO customers VALUES ('c9', 'added later')")
    connection.commit()
    connection.close()
    sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES)

    after = _rows(sync, pinned)

    assert len(before) == 5
    assert after == before, "a pinned read saw rows committed after its snapshot"


def test_an_unpinned_read_DOES_see_it(mirrored):
    """THE CONTROL, and the reason the pin is load-bearing.

    Without it the second page reads the newest data -- exactly the
    duplicate-or-miss the roadmap note describes.
    """
    sync, source = mirrored
    connection = sqlite3.connect(source)
    connection.execute("INSERT INTO customers VALUES ('c9', 'added later')")
    connection.commit()
    connection.close()
    sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES)

    assert len(_rows(sync, None)) == 6


def test_a_new_generation_picks_up_the_new_snapshot(mirrored):
    # The pin must not be permanent. A reload is how a deployment moves
    # to newer data, and a generation that never advanced would serve
    # yesterday's mirror forever.
    sync, source = mirrored
    connection = sqlite3.connect(source)
    connection.execute("INSERT INTO customers VALUES ('c9', 'added later')")
    connection.commit()
    connection.close()
    sync.sync_table("primary", "customers", "customer_id", COLUMNS, TYPES)

    assert len(_rows(sync, _snapshot_of(sync))) == 6
