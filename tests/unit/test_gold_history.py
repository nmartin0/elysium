"""
What changed between two gold publications (GOLD-4).

WHY AT GOLD. A changelog is worth keeping about things people refer
to, and people refer to OBJECTS: "when did this customer's region
change", not "when did cust_region change in table customers". Gold is
the first layer where a row IS an object, so a change recorded here
reads back in the words the question was asked in.

IT DIFFS PUBLICATIONS. Every publication is tagged, so "the previous
one" exists and can be read exactly. Two syncs that changed nothing
produce no publication and therefore no history -- which is correct,
because nothing happened.

AND NO DUCKDB, though the roadmap expected one. D5 accepted it "when
the changelog lands", on 76 ms for 200,000 rows. Measured before
adding it: the pure-Python diff already in the tree takes 377 ms for
the same 200,000. Five times slower and irrelevant beside a sync that
takes seconds.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.changelog import diff_snapshots
from core.mirror.gold import build_gold
from core.mirror.gold_history import CHANGELOG_NAMESPACE, history_for, record_publication
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "p", "table": "customers", "id_column": "cust_pk"},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data"},
        "name": {"type": "data"},
    },
}
START = [("c1", "us-west", "Ada"), ("c2", "us-east", "Ben"), ("c3", "eu", "Cleo")]


@pytest.fixture
def deployment(tmp_path):
    """A source, a sync and a gold build -- runnable repeatedly."""
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE customers (cust_pk TEXT PRIMARY KEY, region TEXT, name TEXT)")
    conn.executemany("INSERT INTO customers VALUES (?,?,?)", START)
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})

    def publish():
        sync.sync_table("p", "customers", "cust_pk", ["cust_pk", "region", "name"],
                        dict.fromkeys(["cust_pk", "region", "name"], "string"))
        silver = sync._catalog.load_table("p.customers").scan().to_arrow().to_pylist()
        return build_gold(sync._catalog, "Customer", TYPE, silver)

    def change(*statements):
        conn = sqlite3.connect(source)
        for statement in statements:
            conn.execute(statement)
        conn.commit()
        conn.close()

    return sync, publish, change


class TestWhatIsRecorded:
    def test_a_first_publication_records_nothing(self, deployment):
        """Writing every existing row as an INSERT would claim a
        history that did not happen."""
        _, publish, _ = deployment

        assert publish().history_rows == 0

    def test_an_update_an_insert_and_a_delete(self, deployment):
        sync, publish, change = deployment
        publish()
        change("UPDATE customers SET region='us-east' WHERE cust_pk='c1'",
               "DELETE FROM customers WHERE cust_pk='c3'",
               "INSERT INTO customers VALUES ('c4','eu','Dmitri')")

        result = publish()

        assert result.history_rows == 3
        kinds = {oid: history_for(sync._catalog, "Customer", "customer_id", oid)[0]["change"]
                 for oid in ("c1", "c3", "c4")}
        assert kinds == {"c1": "UPDATE", "c3": "DELETE", "c4": "INSERT"}

    def test_a_delete_keeps_the_row_as_it_last_stood(self, deployment):
        """The only version of it that will ever exist again."""
        sync, publish, change = deployment
        publish()
        change("DELETE FROM customers WHERE cust_pk='c3'")
        publish()

        entry = history_for(sync._catalog, "Customer", "customer_id", "c3")[0]

        assert entry["values"]["name"] == "Cleo" and entry["values"]["region"] == "eu"

    def test_an_unchanged_object_has_no_history(self, deployment):
        sync, publish, change = deployment
        publish()
        change("UPDATE customers SET region='us-east' WHERE cust_pk='c1'")
        publish()

        assert history_for(sync._catalog, "Customer", "customer_id", "c2") == []

    def test_a_publication_that_changed_nothing_records_nothing(self, deployment):
        _, publish, _ = deployment
        publish()

        assert publish().history_rows == 0

    def test_history_accumulates_across_publications(self, deployment):
        sync, publish, change = deployment
        publish()
        change("UPDATE customers SET region='eu' WHERE cust_pk='c1'")
        publish()
        change("UPDATE customers SET name='Ada Okafor' WHERE cust_pk='c1'")
        publish()

        entries = history_for(sync._catalog, "Customer", "customer_id", "c1")

        assert [entry["change"] for entry in entries] == ["UPDATE", "UPDATE"]
        assert entries[0]["changed_at"] <= entries[1]["changed_at"]

    def test_each_entry_names_the_publication_it_belongs_to(self, deployment):
        sync, publish, change = deployment
        publish()
        change("UPDATE customers SET region='eu' WHERE cust_pk='c1'")
        publish()

        entry = history_for(sync._catalog, "Customer", "customer_id", "c1")[0]

        assert entry["publication"] and entry["changed_at"]


class TestWhatIsRefused:
    def test_a_suspected_partial_read_records_nothing(self, deployment):
        """A changelog full of imaginary deletions is worse than a gap,
        because a gap is visible.

        THE GUARD LIVES IN diff_snapshots, which returns no rows at all
        in this case -- checking it again in record_publication was
        dead code, found because the control that removed it could not
        fail. So both are asserted: the guarantee, and the behaviour
        that depends on it."""
        sync, publish, _ = deployment
        publish()
        previous = [{"customer_id": f"c{n}", "region": "eu"} for n in range(10)]
        current = [{"customer_id": "c1", "region": "eu"}]      # 90% gone

        changes = diff_snapshots(previous, current, "customer_id")
        recorded = record_publication(
            sync._catalog, "Customer", "customer_id", previous, current,
            "2026-01-01T00:00:00+00:00", 1,
        )

        assert changes.suspected_partial_read and changes.rows == []
        assert recorded == 0

    def test_history_is_APPENDED_never_rewritten(self, deployment):
        """History that can be rewritten is not history."""
        sync, publish, change = deployment
        publish()
        change("UPDATE customers SET region='eu' WHERE cust_pk='c1'")
        publish()
        change("UPDATE customers SET region='us-west' WHERE cust_pk='c1'")
        publish()

        table = sync._catalog.load_table(f"{CHANGELOG_NAMESPACE}.Customer")

        assert table.scan().to_arrow().num_rows == 2

    def test_a_type_with_no_history_answers_empty(self, deployment):
        sync, _, _ = deployment

        assert history_for(sync._catalog, "Nothing", "customer_id", "c1") == []


class TestItNeverBreaksAPublication:
    def test_a_failing_changelog_leaves_gold_published(self, deployment, monkeypatch):
        """Gold is published; failing to DESCRIBE the change afterwards
        must not undo that."""
        sync, publish, change = deployment
        publish()
        change("UPDATE customers SET region='eu' WHERE cust_pk='c1'")
        import core.mirror.gold_history as history_module

        def explode(*args, **kwargs):
            raise RuntimeError("the changelog is broken")
        monkeypatch.setattr(history_module, "record_publication", explode)

        result = publish()

        assert result.published and result.history_rows == 0
        rows = sync._catalog.load_table("gold.Customer").scan().to_arrow().to_pylist()
        assert {row["customer_id"] for row in rows} == {"c1", "c2", "c3"}
