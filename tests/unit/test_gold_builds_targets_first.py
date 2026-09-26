"""
A type is built after the types it links to (PA001-G8).

THE LINK AUDIT ASKS THE TARGET'S PUBLICATION whether an id exists.
Built in declaration order, a type could be audited against its
target's PREVIOUS publication -- so a new target row and a new row
referencing it, arriving in the SAME sync, refused the referrer for
pointing at a row published seconds later.

MEASURED, with types deliberately named so declaration order is
wrong:

    REFUSED gold.AOrder: 1 customer value(s) point at no ZCustomer: 'c2'
    published gold.ZCustomer: 2 rows

Nothing was wrong with the data. Rename the type and the refusal
moves -- which is the clearest sign a check is measuring the wrong
thing.

A CYCLE CANNOT BE ORDERED, and the audit says so: "mutually-linked
types cannot both be ordered first". Those keep their declaration
order, which is no worse than before. The deeper fix is PR001-R18
(dependency-aware builds) or auditing links after every type is
built; this is the ordering, which costs nothing and fixes the common
case.

DECLARATION ORDER IS THE TIE-BREAK, so a schema with no links builds
exactly as it did before. A reordering that shuffled unrelated types
would make every failure harder to reproduce.
"""

import sqlite3
from types import SimpleNamespace

import pytest

import scripts.run_sync as run_sync
from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from scripts.run_sync import _targets_before_referrers


def _link(target):
    return {"type": "link", "target": target}


class TestTheOrdering:
    def test_a_target_is_built_before_its_referrer(self):
        schema = {"AOrder": {"fields": {"c": _link("ZCustomer")}},
                   "ZCustomer": {"fields": {}}}

        assert [n for n, _ in _targets_before_referrers(schema)] == \
            ["ZCustomer", "AOrder"]

    def test_a_chain_is_ordered_end_first(self):
        schema = {"A": {"fields": {"b": _link("B")}},
                   "B": {"fields": {"c": _link("C")}},
                   "C": {"fields": {}}}

        assert [n for n, _ in _targets_before_referrers(schema)] == ["C", "B", "A"]

    def test_a_schema_with_no_links_is_untouched(self):
        """Declaration order is the tie-break. Shuffling unrelated
        types would make every failure harder to reproduce."""
        schema = {"X": {"fields": {}}, "Y": {"fields": {}}, "Z": {"fields": {}}}

        assert [n for n, _ in _targets_before_referrers(schema)] == ["X", "Y", "Z"]

    def test_a_cycle_falls_back_to_declaration_order(self):
        """No ordering satisfies a cycle. Refusing to build would be
        worse than auditing against the previous publication, which is
        what happened before."""
        schema = {"A": {"fields": {"b": _link("B")}},
                   "B": {"fields": {"a": _link("A")}}}

        assert [n for n, _ in _targets_before_referrers(schema)] == ["A", "B"]

    def test_every_type_is_built_exactly_once(self):
        """A reordering that dropped or duplicated a type would be far
        worse than the bug it fixed."""
        schema = {"A": {"fields": {"b": _link("B")}},
                   "B": {"fields": {"c": _link("C"), "a": _link("A")}},
                   "C": {"fields": {}}, "D": {"fields": {}}}

        built = [n for n, _ in _targets_before_referrers(schema)]

        assert sorted(built) == ["A", "B", "C", "D"]

    def test_a_link_to_a_type_that_is_not_in_the_schema_is_ignored(self):
        """A dangling declaration must not hang the ordering."""
        schema = {"A": {"fields": {"b": _link("Missing")}}}

        assert [n for n, _ in _targets_before_referrers(schema)] == ["A"]

    def test_a_self_link_does_not_deadlock(self):
        """A type linking to ITSELF -- a parent/child hierarchy -- must
        still build.

        HONEST NOTE: excluding self from a type's own targets is
        clarity, not a guard. A control that removed it left this
        passing, because a self-link then looks like a one-type cycle
        and the cycle fallback builds it anyway. The exclusion says
        what is meant; the fallback is what makes it safe."""
        schema = {"A": {"fields": {"parent": _link("A")}}}

        assert [n for n, _ in _targets_before_referrers(schema)] == ["A"]


class TestThroughARealBuild:
    @pytest.fixture
    def deployment(self, tmp_path):
        source = tmp_path / "s.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT, "
                     "region TEXT)")
        conn.execute("CREATE TABLE customers (id TEXT PRIMARY KEY, name TEXT, "
                     "region TEXT)")
        conn.execute("INSERT INTO customers VALUES ('c1','Ada','us-west')")
        conn.execute("INSERT INTO orders VALUES ('o1','c1','us-west')")
        conn.commit()
        conn.close()
        # NAMED so declaration order is WRONG: the referrer sorts first.
        schema = {
            "AOrder": {"id_field": "id", "security": {"field": "region"},
                        "storage": {"silo": "p", "table": "orders",
                                     "id_column": "id"},
                        "fields": {"id": {"type": "data"},
                                    "region": {"type": "data"},
                                    "customer": {"type": "link",
                                                  "target": "ZCustomer",
                                                  "column": "customer_id"}}},
            "ZCustomer": {"id_field": "id", "security": {"field": "region"},
                           "storage": {"silo": "p", "table": "customers",
                                        "id_column": "id"},
                           "fields": {"id": {"type": "data"},
                                       "name": {"type": "data"},
                                       "region": {"type": "data"}}},
        }
        sync = IcebergMirrorSync(tmp_path / "m",
                                  {"p": SQLiteReadAdapter({"path": source})})
        columns = {"orders": ["id", "customer_id", "region"],
                    "customers": ["id", "name", "region"]}

        def resync():
            for table, cols in columns.items():
                sync.sync_table("p", table, "id", cols, {})

        def add_linked_pair():
            conn = sqlite3.connect(source)
            conn.execute("INSERT INTO customers VALUES ('c2','Bram','us-west')")
            conn.execute("INSERT INTO orders VALUES ('o2','c2','us-west')")
            conn.commit()
            conn.close()

        resync()
        sync.config = SimpleNamespace(schema=schema, identity_inference=False,
                                       retain_publications=30, mirror_storage={})
        sync.resync, sync.add_linked_pair = resync, add_linked_pair
        return sync, tmp_path

    def test_a_new_row_and_its_new_target_publish_together(self, deployment):
        """THE REGRESSION TEST. Both arrive in one sync; neither is at
        fault; the referrer was refused."""
        sync, data_dir = deployment
        run_sync._build_gold(sync, sync.config, data_dir, unsynced=set())

        sync.add_linked_pair()
        sync.resync()
        refused = run_sync._build_gold(sync, sync.config, data_dir, unsynced=set())

        assert refused == 0

    def test_and_both_tables_hold_the_new_rows(self, deployment):
        sync, data_dir = deployment
        run_sync._build_gold(sync, sync.config, data_dir, unsynced=set())
        sync.add_linked_pair()
        sync.resync()
        run_sync._build_gold(sync, sync.config, data_dir, unsynced=set())

        for object_type, expected in (("ZCustomer", 2), ("AOrder", 2)):
            table = sync.catalog.load_table(f"gold.{object_type}")
            assert table.scan().to_arrow().num_rows == expected

    def test_a_genuinely_dangling_link_is_still_refused(self, deployment):
        """The check must keep working. An order pointing at a
        customer that does not exist ANYWHERE is a real fault."""
        sync, data_dir = deployment
        run_sync._build_gold(sync, sync.config, data_dir, unsynced=set())
        conn = sqlite3.connect(sync.adapters["p"].db_path)
        conn.execute("INSERT INTO orders VALUES ('o9','nosuchcustomer','us-west')")
        conn.commit()
        conn.close()
        sync.resync()

        refused = run_sync._build_gold(sync, sync.config, data_dir, unsynced=set())

        assert refused == 1
