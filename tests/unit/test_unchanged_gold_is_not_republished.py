"""
A gold type built from the same inputs as its publication is not
published again (PA001-G11).

MEASURED BEFORE: two builds from one unchanged silver gave two
`published-N` tags and two snapshots holding the same rows -- the
waste silver stopped making long ago ("source unchanged, no new
snapshot written"), still made one layer up.

THE TEST IS ON INPUTS, NOT ROWS. Gold is derived from the silver
snapshots it reads, the type's declaration, approved merges, the ids
its links are audited against, and the code. When none moved, the
publication is what the build would produce; nothing has to be read to
know that, which matters because the common path STREAMS silver and
never holds the rows to compare.
"""

import sqlite3
from types import SimpleNamespace

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.gold import (
    CURRENT_AT_PROPERTY,
    INPUTS_PROPERTY,
    build_gold,
    published_at,
)
from core.mirror.iceberg_sync import IcebergMirrorSync
from scripts import run_sync

SCHEMA = {
    "Order": {"id_field": "id", "security": {"field": "region"},
              "storage": {"silo": "p", "table": "orders", "id_column": "id"},
              "fields": {"id": {"type": "data"}, "region": {"type": "data"},
                         "customer": {"type": "link", "target": "Customer",
                                      "column": "customer_id"}}},
    "Customer": {"id_field": "id", "security": {"field": "region"},
                 "storage": {"silo": "p", "table": "customers", "id_column": "id"},
                 "fields": {"id": {"type": "data"}, "name": {"type": "data"},
                            "region": {"type": "data"}}},
}
COLUMNS = {"orders": ["id", "customer_id", "region"], "customers": ["id", "name", "region"]}


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT, region TEXT)")
    conn.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT, region TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1','Ada','us-west')")
    conn.execute("INSERT INTO orders VALUES ('o1','c1','us-west')")
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "m", {"p": SQLiteReadAdapter({"path": source})})
    sync.config = SimpleNamespace(schema=SCHEMA, identity_inference=False,
                                  retain_publications=30, mirror_storage={})

    def resync():
        for table, columns in COLUMNS.items():
            sync.sync_table("p", table, "id", columns, {})

    def change(statement):
        conn = sqlite3.connect(source)
        conn.execute(statement)
        conn.commit()
        conn.close()
        resync()

    def build():
        return run_sync._build_gold(sync, sync.config, tmp_path, unsynced=set())

    def tags(object_type):
        table = sync.catalog.load_table(f"gold.{object_type}")
        return sorted(name for name in table.refs() if name.startswith("published-"))

    resync()
    return SimpleNamespace(sync=sync, build=build, change=change, tags=tags)


class TestNothingChanged:
    def test_a_second_build_publishes_nothing(self, deployment):
        """THE REGRESSION TEST: one tag, not two."""
        deployment.build()
        deployment.build()

        assert deployment.tags("Customer") == ["published-1"]
        assert deployment.tags("Order") == ["published-1"]

    def test_the_run_says_so_and_is_not_a_failure(self, deployment, capsys):
        deployment.build()
        assert deployment.build() == 0

        assert "unchanged gold.Customer" in capsys.readouterr().out

    def test_published_at_still_moves(self, deployment):
        """PA001-A5's lesson, one layer up: the build looked and found it
        current, so a reader's freshness must not say otherwise."""
        deployment.build()
        before = published_at(deployment.sync.catalog, ["Customer"])["Customer"]
        deployment.build()

        table = deployment.sync.catalog.load_table("gold.Customer")
        assert table.properties.get(CURRENT_AT_PROPERTY)
        assert published_at(deployment.sync.catalog, ["Customer"])["Customer"] > before


class TestSomethingChanged:
    def test_a_changed_row_publishes(self, deployment):
        deployment.build()
        deployment.change("UPDATE customers SET name='Ada L' WHERE id='c1'")
        deployment.build()

        assert deployment.tags("Customer") == ["published-1", "published-2"]

    def test_after_a_change_it_settles_again(self, deployment):
        """Every publication restamps, not only the first -- otherwise the
        stamp describes the FIRST build and nothing after a change is
        ever skipped."""
        deployment.build()
        deployment.change("UPDATE customers SET name='Ada L' WHERE id='c1'")
        deployment.build()
        deployment.build()

        assert deployment.tags("Customer") == ["published-1", "published-2"]

    def test_a_link_target_that_changed_rebuilds_the_referrer(self, deployment):
        """The referrer's rows did not move, but the ids its links are
        audited against did -- so its audit could answer differently."""
        deployment.build()
        deployment.change("INSERT INTO customers VALUES ('c2','Bram','us-west')")
        deployment.build()

        assert deployment.tags("Order") == ["published-1", "published-2"]

    def test_an_unrelated_type_changing_does_not(self, deployment):
        """Customer does not link to Order, so Order changing is not
        Customer's input."""
        deployment.build()
        deployment.change("INSERT INTO orders VALUES ('o2','c1','us-west')")
        deployment.build()

        assert deployment.tags("Customer") == ["published-1"]
        assert deployment.tags("Order") == ["published-1", "published-2"]

    def test_a_changed_declaration_rebuilds(self, deployment):
        deployment.build()
        customer = dict(SCHEMA["Customer"])
        customer["fields"] = {**customer["fields"], "name": {"type": "data", "display_name": "Name"}}
        deployment.sync.config.schema = {**SCHEMA, "Customer": customer}
        deployment.build()

        assert deployment.tags("Customer") == ["published-1", "published-2"]


class TestNeverSkipWrongly:
    def test_a_refused_build_leaves_no_stamp(self, deployment):
        """A dangling link is refused. Built again from the SAME inputs it
        must be refused again, not skipped as if it had published."""
        deployment.build()
        deployment.change("INSERT INTO orders VALUES ('o9','nosuchcustomer','us-west')")

        assert deployment.build() == 1
        assert deployment.build() == 1

    def test_without_a_fingerprint_it_always_builds(self, deployment):
        sync = deployment.sync
        silver = sync.catalog.load_table("p.customers").scan().to_arrow().to_pylist()
        build_gold(sync.catalog, "Customer", SCHEMA["Customer"], silver)
        second = build_gold(sync.catalog, "Customer", SCHEMA["Customer"], silver)

        assert second.published and not second.unchanged
        assert INPUTS_PROPERTY not in sync.catalog.load_table("gold.Customer").properties

    def test_a_current_snapshot_that_was_never_published_is_not_skipped(self, deployment):
        """PA001-G4's crash state: rows appended, never tagged. Skipping
        on it would leave it unpublished for ever."""
        sync = deployment.sync
        silver = sync.catalog.load_table("p.customers").scan().to_arrow().to_pylist()
        build_gold(sync.catalog, "Customer", SCHEMA["Customer"], silver, inputs="x")
        table = sync.catalog.load_table("gold.Customer")
        table.append(table.scan().to_arrow())          # a snapshot nobody published

        again = build_gold(sync.catalog, "Customer", SCHEMA["Customer"], silver, inputs="x")
        assert not again.unchanged


def test_the_code_is_an_input():
    """New code must never be mistaken for the code a publication was
    built by: the digest covers core/mirror and core/ontology."""
    from pathlib import Path

    digest = run_sync._gold_code_version()
    assert len(digest) == 64
    root = Path(run_sync.__file__).resolve().parents[1] / "core"
    assert (root / "mirror" / "gold.py").exists()
