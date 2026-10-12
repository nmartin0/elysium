"""Field classifications reach every table that holds the values (R12).

FOUNDRY'S RULE, which these tests hold the mirror to: "If a dataset has
a file marking, every dataset that depends on it inherits that marking."
A field's values are copied into bronze, silver, the changelog, gold
and gold's history; a label on the ontology property alone describes
one of them.

THE END-TO-END TESTS RUN THE REAL SYNC over the shipped configuration,
which now classifies Customer.email as `pii` and Transaction.amount as
`financial`, and read the properties back from the real catalog.
"""

import contextlib
import io
import json

import pytest

from core.mirror.catalog import open_mirror_catalog
from core.mirror.classifications import (
    CLASSIFICATIONS_PROPERTY,
    classifications_by_table,
    recorded_classifications,
)
from core.ontology.classifications import validate_field_classification
from scripts.run_sync import run_sync

SCHEMA = {
    "Customer": {
        "id_field": "customer_id",
        "storage": {"silo": "primary_sql", "table": "customers", "id_column": "customer_id"},
        "additional_storage": {
            "risk_db": {"silo": "risk_sql", "table": "customer_risk", "id_column": "cust_ref"},
        },
        "fields": {
            "name": {"type": "data"},
            "email": {"type": "data", "classification": "pii"},
            # A DIFFERENT COLUMN NAME IN A DIFFERENT SILO: the label must
            # land on `score_val` in risk_sql, which is where the value is.
            "risk_score": {"type": "data", "storage": "risk_db", "column": "score_val",
                           "classification": ["financial", "pii"]},
            "transactions": {"type": "link", "target": "Transaction", "cardinality": "many"},
        },
    },
    "Transaction": {
        "id_field": "transaction_id",
        "storage": {"silo": "primary_sql", "table": "transactions",
                    "id_column": "transaction_id"},
        "fields": {"category": {"type": "data"}},
    },
}


class TestWhereTheLabelsGo:
    def test_every_copy_of_the_column_carries_it(self):
        tables = classifications_by_table(SCHEMA)

        for identifier in ("bronze_primary_sql.customers", "primary_sql.customers",
                           "changelog_primary_sql.customers"):
            assert tables[identifier] == {"email": ["pii"]}, identifier
        assert tables["gold.Customer"] == {"email": ["pii"], "risk_score": ["financial", "pii"]}

    def test_a_field_in_another_silo_is_labelled_where_its_column_lives(self):
        tables = classifications_by_table(SCHEMA)

        assert tables["risk_sql.customer_risk"] == {"score_val": ["financial", "pii"]}
        assert tables["bronze_risk_sql.customer_risk"] == {"score_val": ["financial", "pii"]}

    def test_a_column_holding_any_field_s_values_carries_every_label(self):
        """Quarantine, history and conflicts hold values of MANY fields
        in one column, so they carry the union -- Foundry's direction:
        a derived dataset inherits everything it depends on."""
        tables = classifications_by_table(SCHEMA)

        assert tables["quarantine_primary_sql.customers"] == {"value": ["pii"]}
        assert tables["gold_history.Customer"] == {"values": ["financial", "pii"]}
        assert tables["gold_conflicts.Customer"] == {
            "chosen": ["financial", "pii"], "losing": ["financial", "pii"]}

    def test_an_unclassified_type_appears_nowhere(self):
        """THE CONTROL: no label is invented for a type that declared none."""
        tables = classifications_by_table(SCHEMA)

        assert not any("transactions" in identifier or "Transaction" in identifier
                       for identifier in tables)


class TestWhatALabelMayBe:
    def test_a_bad_label_stops_the_ontology_loading(self):
        """AT LOAD, not at the sync that would have written it."""
        from core.ontology.object_type_validation import validate_object_types

        with pytest.raises(ValueError, match="'PII'"):
            validate_object_types({"T": {"id_field": "id", "security": {"field": "region"},
                                         "fields": {
                "region": {"type": "data"},
                "f": {"type": "data", "classification": "PII"}}}})

    def test_a_good_label_loads(self):
        """THE CONTROL for the test above, which once passed for the
        wrong reason: its fixture had no security block, and THAT was
        the error raised."""
        from core.ontology.object_type_validation import validate_object_types

        validate_object_types({"T": {"id_field": "id", "security": {"field": "region"},
                                     "fields": {
            "region": {"type": "data"},
            "f": {"type": "data", "classification": "pii"}}}})

    @pytest.mark.parametrize("declared", ["pii", ["pii", "financial"], "special_category_2"])
    def test_accepted(self, declared):
        validate_field_classification("T", "f", {"classification": declared})

    @pytest.mark.parametrize("declared", ["PII", "pii ", "", [], ["pii", 3], {"pii": True}])
    def test_refused(self, declared):
        with pytest.raises(ValueError, match="classification"):
            validate_field_classification("T", "f", {"classification": declared})


def _sync(paths) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
        assert run_sync(paths) == 0


def _properties(paths) -> dict[str, dict]:
    catalog = open_mirror_catalog(paths.data_dir / "mirror")
    found = {}
    for namespace in catalog.list_namespaces():
        for parts in catalog.list_tables(namespace):
            identifier = ".".join(parts)
            labels = recorded_classifications(catalog.load_table(identifier))
            if labels:
                found[identifier] = labels
    return found


class TestTheRealSyncRecordsThem:
    def test_the_shipped_labels_reach_bronze_silver_and_gold(self, synced_deployment):
        found = _properties(synced_deployment)

        for identifier in ("bronze_primary_sql.customers", "primary_sql.customers",
                           "gold.Customer"):
            assert found[identifier]["email"] == ["pii"], identifier
        assert found["gold.Transaction"]["amount"] == ["financial"]
        assert found["primary_sql.transactions"]["amount"] == ["financial"]

    def test_an_unclassified_column_is_not_labelled(self, synced_deployment):
        found = _properties(synced_deployment)

        assert "name" not in found["gold.Customer"]
        assert "region" not in found["primary_sql.customers"]

    def test_a_label_removed_from_the_ontology_comes_off_every_table(self, synced_deployment):
        """OTHERWISE A COLUMN WOULD STILL SAY IT HOLDS PII after the
        ontology stopped saying so."""
        assert _properties(synced_deployment)["gold.Customer"]["email"] == ["pii"]
        ontology = synced_deployment.config_dir / "ontology_schema.yaml"
        ontology.write_text(ontology.read_text().replace("        classification: pii\n", ""))

        _sync(synced_deployment)
        found = _properties(synced_deployment)

        assert not any("email" in labels for labels in found.values())
        # ...while the label nobody removed stays.
        assert found["gold.Transaction"]["amount"] == ["financial"]

    def test_it_is_a_property_readable_without_elysium(self, synced_deployment):
        """Anything that reads an Iceberg catalog -- a backup, an
        auditor, a REST catalog later (R17) -- reads plain JSON."""
        catalog = open_mirror_catalog(synced_deployment.data_dir / "mirror")
        raw = catalog.load_table("gold.Customer").properties[CLASSIFICATIONS_PROPERTY]

        assert json.loads(raw)["email"] == ["pii"]


class TestTheSchemaSaysSo:
    def test_one_bare_label_arrives_as_a_list(self):
        """The ontology may write `classification: pii`; a client always
        reads a list, so it never has to ask which it got."""
        from api.routes import SchemaFieldResponse

        bare = SchemaFieldResponse(type="data", display_name="Email", classification="pii")
        none = SchemaFieldResponse(type="data", display_name="Name")

        assert bare.classification == ["pii"]
        assert none.classification == []
