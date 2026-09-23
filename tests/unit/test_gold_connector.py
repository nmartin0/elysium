"""
Reading gold from inside Elysium (GOLD-3b).

NOT AN ADAPTER, deliberately: adapters read the customer's systems,
with credentials, a network, drift and untrusted data; a connector
reads data Elysium wrote itself, with none of that and a pinned
snapshot. It shares only the Iceberg machinery, through
IcebergNamespaceReader, because those fixes (E-10, F-20, F-01) must
exist once.

IT IS ASKED IN THE ONTOLOGY'S TERMS. The mediator hands it a
type_config from the GOLD VIEW, where a table is an OBJECT TYPE and a
column is a PROPERTY -- so a silo, a source table and a source column
name are words the connector never sees.
"""

import inspect
import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.filters import FieldFilter
from core.mirror.gold import build_gold
from core.mirror.gold_connector import GoldConnector, GoldPublicationMissing
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter
from core.ontology.gold_view import build_gold_view

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "security": {"field": "region"},
        "storage": {"silo": "p", "table": "customers", "id_column": "cust_pk"},
        "fields": {
            "customer_id": {"type": "data", "column": "cust_pk"},
            "region": {"type": "data"},
            "name": {"type": "data"},
            "transactions": {"type": "link", "target": "Transaction", "cardinality": "many",
                              "via_table": "txns", "via_column": "cust_fk"},
        },
    },
    "Transaction": {
        "id_field": "transaction_id",
        "security": {"via_field": "customer_id"},
        "storage": {"silo": "p", "table": "txns", "id_column": "txn_pk"},
        "fields": {
            "transaction_id": {"type": "data", "column": "txn_pk"},
            "amount": {"type": "data", "data_type": "decimal"},
            "customer_id": {"type": "link", "target": "Customer", "cardinality": "one",
                             "column": "cust_fk"},
        },
    },
}


@pytest.fixture
def gold(tmp_path):
    """A real source, synced to silver, built into gold."""
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.executescript("""
        CREATE TABLE customers (cust_pk TEXT PRIMARY KEY, region TEXT, name TEXT);
        INSERT INTO customers VALUES ('c1', 'us-west', 'Ada Okafor');
        INSERT INTO customers VALUES ('c2', 'us-east', 'Ben Carter');
        CREATE TABLE txns (txn_pk TEXT PRIMARY KEY, amount TEXT, cust_fk TEXT);
        INSERT INTO txns VALUES ('t1', '49.99', 'c1');
        INSERT INTO txns VALUES ('t2', '120.50', 'c1');
        INSERT INTO txns VALUES ('t3', '8.25', 'c2');
    """)
    conn.commit()
    conn.close()
    sync = IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})
    sync.sync_table("p", "customers", "cust_pk", ["cust_pk", "region", "name"],
                    dict.fromkeys(["cust_pk", "region", "name"], "string"))
    sync.sync_table("p", "txns", "txn_pk", ["txn_pk", "amount", "cust_fk"],
                    {"txn_pk": "string", "amount": "decimal", "cust_fk": "string"})
    for object_type, type_def in SCHEMA.items():
        silver = sync._catalog.load_table(
            f"p.{type_def['storage']['table']}").scan().to_arrow().to_pylist()
        result = build_gold(sync._catalog, object_type, type_def, silver)
        assert result.published, result.problems
    view, _ = build_gold_view(SCHEMA)
    return GoldConnector(sync._catalog), view


class TestItSpeaksTheOntologysTerms:
    def test_find_ids_filters_by_a_PROPERTY(self, gold):
        connector, view = gold

        found = connector.find_ids(
            "Customer", [FieldFilter("region", "equals", "us-west")], view["Customer"],
        )

        assert found == ["c1"]

    def test_the_id_returned_is_the_objects_id(self, gold):
        """Not the source's primary-key column, which gold renamed."""
        connector, view = gold

        assert connector.find_ids("Customer", [], view["Customer"]) == ["c1", "c2"]

    def test_get_raw_field_reads_a_property(self, gold):
        connector, view = gold

        assert connector.get_raw_field(
            "Customer", "c1", "name", view["Customer"]) == "Ada Okafor"

    def test_a_property_the_source_called_something_else(self, gold):
        """`cust_pk` in the source; `customer_id` in gold and here."""
        connector, view = gold

        assert connector.get_raw_field(
            "Customer", "c2", "customer_id", view["Customer"]) == "c2"

    def test_read_fields_for_ids_returns_rows_keyed_by_property(self, gold):
        connector, view = gold

        rows = connector.read_fields_for_ids(
            "Customer", "customer_id", ["c1", "c2"], ["name", "region"], view["Customer"],
        )

        assert sorted(row["name"] for row in rows) == ["Ada Okafor", "Ben Carter"]

    def test_free_text_searches_the_named_properties(self, gold):
        connector, view = gold

        found = connector.find_ids_matching_text(
            "Customer", ["name", "region"], "okafor", view["Customer"],
        )

        assert found == ["c1"]


class TestTheReKeyedLinks:
    def test_a_reverse_link_resolves_through_the_targets_GOLD_table(self, gold):
        """via_table is the object TYPE and via_column the target's
        PROPERTY -- both rebound by the gold view."""
        connector, view = gold
        field_config = view["Customer"]["fields"]["transactions"]

        found = connector.resolve_reverse_links_batch(
            ["c1", "c2"], field_config, "transaction_id",
        )

        assert sorted(found["c1"]) == ["t1", "t2"] and found["c2"] == ["t3"]

    def test_one_object_at_a_time_agrees_with_the_batch(self, gold):
        connector, view = gold
        field_config = view["Customer"]["fields"]["transactions"]

        assert sorted(connector.resolve_reverse_link(
            "c1", field_config, "transaction_id")) == ["t1", "t2"]

    def test_an_object_with_no_links_is_absent_rather_than_wrong(self, gold):
        connector, view = gold
        field_config = view["Customer"]["fields"]["transactions"]

        assert connector.resolve_reverse_links_batch(
            ["nobody"], field_config, "transaction_id") == {}


class TestWhatItSaysWhenGoldIsNotThere:
    def test_an_unpublished_type_names_itself_and_the_fix(self, gold):
        connector, view = gold
        missing = {**view["Customer"],
                   "storage": {**view["Customer"]["storage"], "table": "Supplier"}}

        with pytest.raises(GoldPublicationMissing, match="Run a sync"):
            connector.find_ids("Supplier", [], missing)

    def test_columns_present_is_empty_rather_than_raising(self, gold):
        connector, _ = gold

        assert connector.columns_present("Supplier") == set()

    def test_the_lake_being_readable_is_a_different_question(self, gold):
        """health_check must not fail because ONE type is unbuilt: that
        would take the deployment down for a condition affecting one."""
        connector, _ = gold

        assert connector.health_check() is None


class TestItIsNotAnAdapter:
    def test_it_answers_everything_the_mediator_asks_of_a_reader(self):
        """A TRIPWIRE. The mediator calls these on whatever it is given;
        if the adapter grows a tenth read method, the connector must
        grow it too -- and this fails until it does."""
        asked = {
            name for name, _ in inspect.getmembers(MirrorReadAdapter, inspect.isfunction)
            if not name.startswith("_")
        }
        # source_column_types is drift detection, which gold does not
        # have: its schema is generated from the declaration, so a
        # mismatch is a bug in us, not news about a source.
        asked.discard("source_column_types")

        missing = {name for name in asked if not hasattr(GoldConnector, name)}

        assert missing == set(), f"the connector cannot answer {sorted(missing)}"

    def test_it_does_NOT_inherit_the_adapter(self):
        """Adapters carry credentials, drift handling and a source's
        failure modes. A connector reading our own lake should not
        inherit that apparatus (the owner, September 22)."""
        assert not issubclass(GoldConnector, MirrorReadAdapter)

    def test_and_shares_the_iceberg_machinery_rather_than_copying_it(self):
        from core.mirror.iceberg_reader import IcebergNamespaceReader

        source = inspect.getsource(GoldConnector)

        assert "IcebergNamespaceReader" in source
        for copied in ("_decimal_literal", "MAX_CACHED_ROWS", "def _term_for"):
            assert copied not in source, f"{copied} looks copied rather than shared"
        assert hasattr(IcebergNamespaceReader, "_decimal_literal")
