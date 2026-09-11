"""
A generation reads ONE snapshot of the mirror -- step 5a of
HOT_RELOAD_PLAN.md.

WHY IT MATTERS. A sync can commit while a query is running. Without a
pin, hop 1 reads Customer as it was BEFORE the sync and hop 5 reads
Transaction as it is AFTER -- an answer assembled from two points in
time that was never true at either. That is the same objection as a
torn configuration read, one layer down.

Iceberg gives snapshot isolation for free. These tests are what asks
for it.

PUBLISHING NEW DATA IS A GENERATION SWAP, not a separate mechanism: the
adapters are pinned when they are built, so a reload is what moves the
mirror forward. One publish covers both the configuration and the data
it describes, which is also why this needs no branch-merge support --
see IDEAS.md on pyiceberg's fast_forward_branch.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter


@pytest.fixture
def source_db(tmp_path):
    path = tmp_path / "source.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1', 'Ada')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def synced(tmp_path, source_db):
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source_db})})
    sync.sync_table("primary", "customers", ["customer_id", "name"], {"customer_id": "string", "name": "string"})
    return sync, source_db


def _resync(sync, source_db, name):
    conn = sqlite3.connect(source_db)
    conn.execute("UPDATE customers SET name = ? WHERE customer_id = 'c1'", (name,))
    conn.commit()
    conn.close()
    sync.sync_table("primary", "customers", ["customer_id", "name"],
                    {"customer_id": "string", "name": "string"})


def _names(adapter):
    rows = adapter._scan("customers", ("customer_id", "name"))
    return rows.to_pydict()["name"]


def test_a_pinned_adapter_does_not_see_a_later_sync(synced, source_db):
    # THE PROPERTY. The pin is what makes a generation's view of the
    # data stable for as long as anything is reading it.
    sync, _ = synced
    snapshot = sync._catalog.load_table("primary.customers").current_snapshot().snapshot_id
    pinned = MirrorReadAdapter(sync._catalog, "primary", snapshot_ids={"customers": snapshot})

    _resync(sync, source_db, "Grace")

    assert _names(pinned) == ["Ada"], "the pinned adapter followed the new sync"


def test_an_unpinned_adapter_sees_the_latest(synced, source_db):
    # THE CONTROL. Without it, the test above could pass because the
    # sync never landed rather than because the pin held.
    sync, _ = synced
    unpinned = MirrorReadAdapter(sync._catalog, "primary")

    _resync(sync, source_db, "Grace")

    assert _names(unpinned) == ["Grace"]


def test_a_new_pin_moves_the_view_forward(synced, source_db):
    # What a reload does: a NEW generation builds new adapters pinned
    # to the snapshots current at that moment. Publishing data and
    # publishing configuration are one operation.
    sync, _ = synced
    _resync(sync, source_db, "Grace")
    latest = sync._catalog.load_table("primary.customers").current_snapshot().snapshot_id

    assert _names(MirrorReadAdapter(sync._catalog, "primary", snapshot_ids={"customers": latest})) == ["Grace"]


def test_a_table_with_no_pin_reads_current_state(synced, source_db):
    # A table synced for the first time AFTER this generation was built
    # has no id to pin. Reading its current state is better than
    # reading nothing, and better than raising -- the mirror is allowed
    # to gain tables between reloads.
    sync, _ = synced
    adapter = MirrorReadAdapter(sync._catalog, "primary", snapshot_ids={"other_table": 1})

    assert _names(adapter) == ["Ada"]


def test_the_pin_survives_a_filtered_scan(synced, source_db):
    # The filter path builds its scan separately, and an early version
    # of this change set snapshot_id on only one of the two branches.
    from core.filters import as_equality_conditions

    sync, _ = synced
    snapshot = sync._catalog.load_table("primary.customers").current_snapshot().snapshot_id
    pinned = MirrorReadAdapter(sync._catalog, "primary", snapshot_ids={"customers": snapshot})
    _resync(sync, source_db, "Grace")

    row_filter = pinned._conditions_to_filter(as_equality_conditions({"customer_id": "c1"}))
    rows = pinned._scan("customers", ("customer_id", "name"), row_filter=row_filter)

    assert rows.to_pydict()["name"] == ["Ada"], "the filtered path ignored the pin"
