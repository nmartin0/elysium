"""
The ontology, and separately where its data comes from (GOLD-3c).

TWO DIFFERENT THINGS HAD BEEN LIVING IN ONE FILE: what an object IS --
its identity, properties, links, what carries its classification --
and where the data comes from, which silo and table and column. The
second is an INGESTION detail, and since GOLD-8 it is not even how
reads work: a read goes to gold, whose table is the object type and
whose columns are the property names.

WHY IT MATTERS THAT THEY ARE APART: a change of source system now
edits source_bindings.yaml, and a change to what a Customer IS edits
ontology_schema.yaml -- so a diff of the second is worth reading,
which it was not when a column rename looked the same as a new
property.

NOTHING DOWNSTREAM CHANGED. The loader merges them into exactly the
schema it produced before, which the first test here asserts against
the shipped deployment.
"""

import json
from pathlib import Path

import pytest
import yaml

from core.deployment_loader import load_deployment
from core.ontology.bindings import merge_bindings, split_bindings

DECLARATION = {
    "Customer": {
        "id_field": "customer_id",
        "security": {"field": "region"},
        "fields": {
            "customer_id": {"type": "data"},
            "region": {"type": "data"},
            "transactions": {"type": "link", "target": "Transaction",
                              "cardinality": "many"},
        },
    },
}
BINDINGS = {
    "Customer": {
        "storage": {"silo": "primary_sql", "table": "customers",
                     "id_column": "cust_pk"},
        "fields": {
            "customer_id": {"column": "cust_pk"},
            "transactions": {"via_table": "txns", "via_column": "cust_fk"},
        },
    },
}


def _plain(value):
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class TestMerging:
    def test_a_type_gains_its_storage(self):
        merged = merge_bindings(DECLARATION, BINDINGS)

        assert merged["Customer"]["storage"]["table"] == "customers"

    def test_a_field_gains_its_column(self):
        merged = merge_bindings(DECLARATION, BINDINGS)

        assert merged["Customer"]["fields"]["customer_id"]["column"] == "cust_pk"

    def test_a_link_gains_the_table_it_is_resolved_through(self):
        merged = merge_bindings(DECLARATION, BINDINGS)

        assert merged["Customer"]["fields"]["transactions"]["via_table"] == "txns"

    def test_what_a_field_MEANS_is_untouched(self):
        merged = merge_bindings(DECLARATION, BINDINGS)

        link = merged["Customer"]["fields"]["transactions"]
        assert link["target"] == "Transaction" and link["cardinality"] == "many"

    def test_a_field_with_no_binding_is_still_there(self):
        merged = merge_bindings(DECLARATION, BINDINGS)

        assert merged["Customer"]["fields"]["region"] == {"type": "data"}


class TestWhatIsRefused:
    def test_a_binding_for_an_undeclared_type(self):
        """Almost always a rename that happened on one side only."""
        with pytest.raises(ValueError, match="does not declare"):
            merge_bindings(DECLARATION, {**BINDINGS, "Ghost": {"storage": {}}})

    def test_a_binding_for_an_undeclared_field(self):
        bindings = {"Customer": {**BINDINGS["Customer"],
                                  "fields": {"nickname": {"column": "nick"}}}}

        with pytest.raises(ValueError, match="does not\\s+declare|not\\s+declare"):
            merge_bindings(DECLARATION, bindings)

    def test_a_declared_type_with_no_binding(self):
        """It could not be ingested, so gold would never publish it --
        and since GOLD-8 that means it could not be served either."""
        with pytest.raises(ValueError, match="no source binding"):
            merge_bindings(DECLARATION, {})


class TestTheRoundTrip:
    def test_splitting_and_merging_gives_back_the_original(self):
        merged = merge_bindings(DECLARATION, BINDINGS)

        declaration, bindings = split_bindings(merged)

        assert merge_bindings(declaration, bindings) == merged

    def test_the_declaration_half_carries_no_bindings(self):
        merged = merge_bindings(DECLARATION, BINDINGS)

        declaration, _ = split_bindings(merged)

        assert "storage" not in declaration["Customer"]
        assert "column" not in declaration["Customer"]["fields"]["customer_id"]
        assert "via_table" not in declaration["Customer"]["fields"]["transactions"]

    def test_and_security_stays_a_DECLARATION(self):
        """WHICH field carries a classification is a fact about the
        ontology, even though the column that field reads is not."""
        merged = merge_bindings(DECLARATION, BINDINGS)

        declaration, bindings = split_bindings(merged)

        assert declaration["Customer"]["security"] == {"field": "region"}
        assert "security" not in bindings["Customer"]


class TestTheShippedDeployment:
    def test_it_loads_to_exactly_what_the_single_file_produced(self):
        """The whole promise of the split: nothing downstream changes."""
        config = load_deployment(Path("deployment/etc"))

        merged = json.dumps(_plain(config.schema), sort_keys=True)

        # Rebuilt from the two files by hand, the way the loader does.
        declaration = yaml.safe_load(
            Path("deployment/etc/ontology_schema.yaml").read_text())
        bindings = yaml.safe_load(
            Path("deployment/etc/source_bindings.yaml").read_text())
        rebuilt = merge_bindings(
            declaration.get("object_types", declaration),
            bindings.get("object_types", bindings),
        )
        assert merged == json.dumps(_plain(rebuilt), sort_keys=True)

    def test_the_ontology_file_no_longer_mentions_a_table(self):
        text = Path("deployment/etc/ontology_schema.yaml").read_text()
        types = yaml.safe_load(text)
        types = types.get("object_types", types)

        for type_def in types.values():
            assert "storage" not in type_def
            for field_config in (type_def.get("fields") or {}).values():
                assert not {"column", "via_table", "via_column"} & set(field_config)

    def test_and_kept_its_comments(self):
        """A split that deleted the prose explaining the decisions
        would have cost more than it bought -- the first version of the
        migration script did exactly that, with yaml.safe_dump."""
        text = Path("deployment/etc/ontology_schema.yaml").read_text()

        comments = [line for line in text.splitlines() if line.strip().startswith("#")]

        assert len(comments) > 50


class TestADeploymentThatHasNotSplit:
    def test_an_ontology_file_with_bindings_still_works(self, tmp_path):
        """Every deployment written before GOLD-3c looks like this, and
        must keep starting."""
        import shutil

        target = tmp_path / "etc"
        shutil.copytree(Path("deployment/etc"), target)
        declaration = yaml.safe_load((target / "ontology_schema.yaml").read_text())
        bindings = yaml.safe_load((target / "source_bindings.yaml").read_text())
        merged = merge_bindings(declaration.get("object_types", declaration),
                                 bindings.get("object_types", bindings))
        (target / "ontology_schema.yaml").write_text(
            yaml.safe_dump({**declaration, "object_types": merged}, sort_keys=False))
        (target / "source_bindings.yaml").unlink()

        config = load_deployment(target)

        assert config.schema["Customer"]["storage"]["table"] == "customers"

    def test_but_binding_in_BOTH_files_is_refused(self, tmp_path):
        """Two places declaring where a table lives is the ambiguity
        the split exists to remove; guessing which wins would be worse
        than refusing."""
        import shutil

        target = tmp_path / "etc"
        shutil.copytree(Path("deployment/etc"), target)
        declaration = yaml.safe_load((target / "ontology_schema.yaml").read_text())
        types = declaration.get("object_types", declaration)
        types["Customer"]["storage"] = {"silo": "x", "table": "y", "id_column": "z"}
        (target / "ontology_schema.yaml").write_text(yaml.safe_dump(declaration))

        with pytest.raises(ValueError, match="still binds"):
            load_deployment(target)
