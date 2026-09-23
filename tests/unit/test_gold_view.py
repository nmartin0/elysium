"""
The ontology's schema rebound to gold (GOLD-3).

The read path is ontology-shaped at its surface and STORAGE-shaped
inside: a field becomes a column, a type becomes a silo and a table.
Gold does not change the surface; it changes those inside facts. So
the view is a TRANSLATION of the declared schema, derived every time,
never stored and never edited -- the declaration stays the only place
an object type is defined (GOLD-3c).

THE RE-KEYING IS THE POINT. A reverse link is resolved by querying the
TARGET's table for rows pointing back; in gold that table is
gold.<Target>, and the key is the target's own PROPERTY name, not the
source column via_column named. Getting this wrong is how F-19 and its
neighbours happened: a chain that loads happily and fails every read.
"""

import pytest

from core.ontology.gold_view import GOLD_NAMESPACE, GOLD_VIEW_MARKER, build_gold_view

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "security": {"field": "region"},
        "storage": {"silo": "primary_sql", "table": "customers", "id_column": "cust_pk"},
        "fields": {
            "customer_id": {"type": "data", "column": "cust_pk"},
            "region": {"type": "data", "column": "cust_region"},
            "transactions": {"type": "link", "target": "Transaction",
                              "cardinality": "many", "via_table": "txns",
                              "via_column": "cust_fk"},
        },
    },
    "Transaction": {
        "id_field": "transaction_id",
        "security": {"via_field": "customer_id"},
        "storage": {"silo": "primary_sql", "table": "txns", "id_column": "txn_pk"},
        "fields": {
            "transaction_id": {"type": "data", "column": "txn_pk"},
            "amount": {"type": "data", "data_type": "decimal"},
            # The source column the reverse link above points at.
            "customer_id": {"type": "link", "target": "Customer",
                             "cardinality": "one", "column": "cust_fk"},
        },
    },
}


@pytest.fixture
def view():
    built, _ = build_gold_view(SCHEMA)
    return built


class TestStorage:
    def test_each_type_becomes_its_own_gold_table(self, view):
        assert view["Customer"]["storage"]["silo"] == GOLD_NAMESPACE
        assert view["Customer"]["storage"]["table"] == "Customer"

    def test_the_key_is_the_id_FIELD_not_the_source_column(self, view):
        """conform() writes the id under the ontology's own name."""
        assert view["Customer"]["storage"]["id_column"] == "customer_id"

    def test_the_view_is_marked_as_one(self, view):
        assert view["Customer"]["storage"][GOLD_VIEW_MARKER] is True

    def test_the_declared_schema_is_not_mutated(self, view):
        assert SCHEMA["Customer"]["storage"]["table"] == "customers"
        assert SCHEMA["Customer"]["fields"]["region"]["column"] == "cust_region"


class TestFields:
    def test_a_column_override_is_dropped(self, view):
        """gold wrote the property under its own name, so a stale
        override would read a column gold never created."""
        assert "column" not in view["Customer"]["fields"]["region"]

    def test_what_a_field_MEANS_is_untouched(self, view):
        amount = view["Transaction"]["fields"]["amount"]

        assert amount["type"] == "data" and amount["data_type"] == "decimal"

    def test_security_is_untouched(self, view):
        assert view["Customer"]["security"] == {"field": "region"}
        assert view["Transaction"]["security"] == {"via_field": "customer_id"}


class TestTheReKeying:
    def test_a_reverse_link_points_at_the_targets_gold_table(self, view):
        assert view["Customer"]["fields"]["transactions"]["via_table"] == "Transaction"

    def test_and_is_keyed_by_the_targets_PROPERTY(self, view):
        """The source said cust_fk; the target declares that column as
        its `customer_id` property, which is what gold stores."""
        assert view["Customer"]["fields"]["transactions"]["via_column"] == "customer_id"

    def test_an_unmapped_column_is_passed_through_honestly(self):
        """Where nothing declares that column, conform() wrote a
        property of the same name -- so passing it through is usually
        right, and a guess would be worse."""
        schema = {
            "A": {"id_field": "a_id", "storage": {"silo": "s", "table": "a", "id_column": "a_id"},
                   "security": {"field": "r"},
                   "fields": {"a_id": {"type": "data"}, "r": {"type": "data"},
                              "bs": {"type": "link", "target": "B", "cardinality": "many",
                                     "via_table": "b", "via_column": "a_ref"}}},
            "B": {"id_field": "b_id", "storage": {"silo": "s", "table": "b", "id_column": "b_id"},
                   "security": {"field": "r"},
                   "fields": {"b_id": {"type": "data"}, "r": {"type": "data"}}},
        }

        built, _ = build_gold_view(schema)

        assert built["A"]["fields"]["bs"]["via_column"] == "a_ref"

    def test_a_forward_link_keeps_its_target_and_loses_its_column(self, view):
        link = view["Transaction"]["fields"]["customer_id"]

        assert link["target"] == "Customer" and "column" not in link


class TestWhatIsLeftOUT:
    def test_a_type_with_several_sources_is_excluded_and_named(self):
        schema = {**SCHEMA}
        schema["Customer"] = {**SCHEMA["Customer"], "additional_storage": {"other": {}}}

        built, excluded = build_gold_view(schema)

        assert "Customer" not in built
        assert "GOLD-5" in excluded["Customer"]

    def test_and_so_is_anything_that_LINKS_to_it(self):
        """A field pointing at a type with no gold table is exactly the
        dangling reference this module exists to avoid."""
        schema = {**SCHEMA}
        schema["Customer"] = {**SCHEMA["Customer"], "additional_storage": {"other": {}}}

        built, excluded = build_gold_view(schema)

        assert built == {}
        assert "Customer" in excluded["Transaction"]

    def test_a_type_without_an_id_field_is_excluded(self):
        schema = {"A": {"storage": {"silo": "s", "table": "a", "id_column": "x"},
                         "security": {"field": "r"}, "fields": {}}}

        built, excluded = build_gold_view(schema)

        assert built == {} and "id_field" in excluded["A"]

    def test_the_shipped_ontology_is_fully_included(self):
        """Both shipped types are single-source, so nothing is lost."""
        import yaml
        schema = yaml.safe_load(open("deployment/etc/ontology_schema.yaml"))

        built, excluded = build_gold_view(schema.get("object_types", schema))

        assert sorted(built) == ["Customer", "Transaction"] and excluded == {}
