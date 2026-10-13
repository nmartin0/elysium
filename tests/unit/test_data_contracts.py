"""Each object type as an ODCS data contract (R16).

TWO THINGS A CONTRACT MUST BE, and each has its own test against an
authority rather than against this code:

  VALID -- checked against the standard's own JSON schema, shipped by
  Bitol as `open-data-contract-standard`, not a hand-written copy.

  TRUE -- checked against the gold table a real sync of the shipped
  deployment WROTE. The first draft promised `decimal(38, 2)` and a
  `long` key; gold held `decimal(38, 9)` and a string. Both were
  caught here, and only here.
"""

import json
from datetime import timedelta
from pathlib import Path

import jsonschema
import open_data_contract_standard
import pytest

from core.deployment_loader import load_deployment
from core.mirror.catalog import open_mirror_catalog
from core.mirror.data_contracts import contract_version, data_contract
from core.mirror.freshness import FreshnessTarget

ODCS_SCHEMA = json.loads(
    (Path(open_data_contract_standard.__file__).parent / "schema.json").read_text())

SCHEMA = {
    "Customer": {
        "id_field": "id", "status": "experimental",
        "description": "A person the business serves.",
        "fields": {
            "name": {"type": "data", "required": True,
                     "constraints": {"min_length": 1, "max_length": 80}},
            "tier": {"type": "data", "constraints": {"one_of": ["gold", "silver"]}},
            "salary": {"type": "data", "data_type": "decimal",
                       "classification": ["pii", "financial"]},
            "orders": {"type": "link", "target": "Order", "cardinality": "many"},
        },
    },
    "Order": {
        "id_field": "id",
        "fields": {"customer": {"type": "link", "target": "Customer", "cardinality": "one"}},
    },
}


def _props(contract):
    return {prop["name"]: prop for prop in contract["schema"][0]["properties"]}


def _valid(contract):
    jsonschema.Draft201909Validator(ODCS_SCHEMA).validate(json.loads(json.dumps(contract)))


class TestValidAgainstTheStandard:
    @pytest.mark.parametrize("config_dir", ["deployment/etc", "tests/integration/fixtures"])
    def test_every_type_in_both_shipped_ontologies(self, config_dir):
        config = load_deployment(Path(config_dir))
        for object_type in config.schema:
            _valid(data_contract(object_type, config.schema,
                                 config.freshness_targets.get(object_type)))

    def test_the_hand_built_one_that_uses_every_mapping(self):
        _valid(data_contract("Customer", SCHEMA, FreshnessTarget(timedelta(hours=26.4),
                                                                 timedelta(hours=50.4))))

    def test_the_validator_is_not_vacuous(self):
        """THE CONTROL: a logical type the standard does not have."""
        contract = data_contract("Customer", SCHEMA)
        contract["schema"][0]["properties"][1]["logicalType"] = "text"

        with pytest.raises(jsonschema.ValidationError):
            _valid(contract)


class TestTrueOfWhatGoldWrote:
    def test_every_column_and_type_the_contract_promises_is_in_gold(self, synced_deployment):
        config = load_deployment(synced_deployment.config_dir)
        catalog = open_mirror_catalog(synced_deployment.data_dir / "mirror")
        for object_type in config.schema:
            columns = {f.name: str(f.field_type)
                       for f in catalog.load_table(f"gold.{object_type}").schema().fields}
            promised = {name: prop["physicalType"]
                        for name, prop in _props(data_contract(object_type, config.schema)).items()}

            assert {name: columns.get(name) for name in promised} == promised, object_type
            # ...and gold holds nothing a consumer could rely on that the
            # contract does not name, beyond the system columns.
            undeclared = {name for name in columns if not name.startswith("_")} - set(promised)
            assert undeclared == set(), object_type


class TestTheMapping:
    def test_the_key_comes_first_and_is_the_primary_key(self):
        key = data_contract("Customer", SCHEMA)["schema"][0]["properties"][0]

        assert key["name"] == "id"
        assert key["primaryKey"] is True and key["required"] is True

    def test_a_reverse_link_is_not_a_column(self):
        assert "orders" not in _props(data_contract("Customer", SCHEMA))

    def test_a_stored_link_holds_the_targets_id(self):
        link = _props(data_contract("Order", SCHEMA))["customer"]

        assert link["logicalType"] == "string"
        assert "Customer" in link["description"]

    def test_constraints_become_quality_rules(self):
        props = _props(data_contract("Customer", SCHEMA))

        assert props["name"]["required"] is True
        assert {rule["description"] for rule in props["name"]["quality"]} == {
            "min length 1", "max length 80"}
        assert props["tier"]["quality"] == [{"type": "text",
                                             "description": "one of ['gold', 'silver']"}]

    def test_every_label_is_carried(self):
        salary = _props(data_contract("Customer", SCHEMA))["salary"]

        assert salary["classification"] == "financial, pii"
        assert salary["tags"] == ["classification:financial", "classification:pii"]
        assert salary["physicalType"].startswith("decimal(")

    def test_freshness_is_the_sla_and_an_exempt_type_promises_none(self):
        target = FreshnessTarget(timedelta(hours=26.4), timedelta(hours=50.4))
        (sla,) = data_contract("Customer", SCHEMA, target)["slaProperties"]

        assert (sla["property"], sla["value"], sla["valueExt"], sla["unit"]) == (
            "latency", 26.4, 50.4, "h")
        exempt = FreshnessTarget(target.warn_after, target.fail_after, exempt=True)
        assert "slaProperties" not in data_contract("Customer", SCHEMA, exempt)

    def test_experimental_is_a_draft(self):
        assert data_contract("Customer", SCHEMA)["status"] == "draft"

    def test_the_version_changes_with_the_declaration_and_only_then(self):
        before = contract_version(SCHEMA["Customer"])
        changed = {**SCHEMA["Customer"], "fields": {**SCHEMA["Customer"]["fields"],
                                                   "nickname": {"type": "data"}}}

        assert contract_version(dict(SCHEMA["Customer"])) == before
        assert contract_version(changed) != before


def test_the_export_script_writes_one_file_per_type(private_deployment, tmp_path, capsys):
    from scripts.export_contracts import run

    run(tmp_path / "out", private_deployment)

    written = sorted(path.name for path in (tmp_path / "out").iterdir())
    assert written == sorted(f"{t}.odcs.yaml"
                             for t in load_deployment(private_deployment.config_dir).schema)
