"""
A column added to the ontology is absorbed, not a failure.

STEP 5d OF HOT_RELOAD_PLAN.md, and it turned out to be a LIVE DEFECT
rather than the enhancement the plan described. Without this,
declaring a new field on an existing object type broke that table's
sync outright -- pyiceberg refusing with "PyArrow table contains more
columns" -- and the mirror then served its last good contents forever
while the ontology said something else.

ADDITIVE IS THE SAFE DIRECTION. A column nothing previously read
cannot have been read wrongly, and Foundry treats the same change as a
non-event: "additive changes to the backing dataset do not interfere
with the synchronization process".

Destructive change does not come through here. A removed column is
decided by core/mirror/drift_policy.py before any read happens, and a
type change is refused. This path only ever widens.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.lineage import LINEAGE_COLUMNS

TYPES = {"customer_id": "string", "name": "string", "region": "string"}


@pytest.fixture
def sync(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute(
        "CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT, region TEXT)"
    )
    connection.executemany(
        "INSERT INTO customers VALUES (?, ?, ?)",
        [("c1", "Ada", "us-west"), ("c2", "Bram", "us-east")],
    )
    connection.commit()
    connection.close()
    return IcebergMirrorSync(tmp_path / "mirror", {"primary": SQLiteReadAdapter({"path": source})})


def _source_columns(names):
    """The mirrored columns that came from the SOURCE -- silver also
    carries lineage columns, which these tests are not about (GOLD-1)."""
    return [name for name in names if name not in LINEAGE_COLUMNS]


def _sync(sync, columns):
    return sync.sync_table(
        "primary", "customers", "customer_id", columns,
        {name: TYPES[name] for name in columns},
    )


def _mirrored(sync):
    return sync._catalog.load_table("primary.customers")


def test_a_newly_declared_field_widens_the_mirror(sync):
    # THE DEFECT. Before this, the second sync raised and the table
    # kept its old shape and old contents indefinitely.
    _sync(sync, ["customer_id", "name"])
    # Lineage columns excluded: they are Elysium's, not the source's (GOLD-1).
    assert _source_columns(_mirrored(sync).schema().column_names) == ["customer_id", "name"]

    _sync(sync, ["customer_id", "name", "region"])

    assert "region" in _mirrored(sync).schema().column_names


def test_the_new_column_actually_holds_its_values(sync):
    # A widened schema with empty values would pass the test above and
    # serve nulls for a field the ontology says is populated.
    _sync(sync, ["customer_id", "name"])
    _sync(sync, ["customer_id", "name", "region"])

    rows = _mirrored(sync).scan().to_arrow().to_pydict()

    assert sorted(rows["region"]) == ["us-east", "us-west"]


def test_the_existing_columns_survive(sync):
    # Widening must not be a rebuild. The prior columns and their
    # values are the mirror's whole purpose.
    _sync(sync, ["customer_id", "name"])
    _sync(sync, ["customer_id", "name", "region"])

    rows = _mirrored(sync).scan().to_arrow().to_pydict()

    assert sorted(rows["name"]) == ["Ada", "Bram"]
    assert sorted(rows["customer_id"]) == ["c1", "c2"]


def test_an_unchanged_sync_still_works(sync):
    # THE CONTROL. Running update_schema() on every sync must be a
    # no-op when nothing changed -- the overwhelmingly common case.
    _sync(sync, ["customer_id", "name"])
    result = _sync(sync, ["customer_id", "name"])

    assert result.row_count == 2
    assert _source_columns(_mirrored(sync).schema().column_names) == ["customer_id", "name"]


def test_a_first_sync_of_a_new_table_is_unaffected(sync):
    # The table does not exist yet on the first sync, so the widening
    # path must not assume one.
    result = _sync(sync, ["customer_id", "name", "region"])

    assert result.row_count == 2
    assert "region" in _mirrored(sync).schema().column_names
