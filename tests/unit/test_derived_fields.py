"""
Fields worked out from other fields of the same object (R37).

What the owner chose on 13 October: a fixed set of formulas, checked
when the configuration loads. What these tests hold it to:

  - each formula's arithmetic, including what an empty input does;
  - a formula that could never be computed is refused at load;
  - nobody reads a derived value who may not read every input -- the
    one property that, if it broke, would turn arithmetic into a way
    around a field grant;
  - gold stores it (filters and counts work) and a read recomputes it;
  - it cannot be written.
"""

import contextlib
import io
import shutil
from datetime import date, datetime
from decimal import Decimal

import pyarrow as pa
import pytest

import scripts.seed_dev_silos as seed
from core.deployment_loader import RuntimePaths, load_deployment_bundle
from core.filters import FieldFilter
from core.intermediate_layer.auth import UserRecord
from core.ontology.derived_fields import (
    compute,
    derivation_of,
    fill_result_types,
    finished,
    gate_derived_grants,
    refuse_rules_over_derived,
    result_type,
    validate_derived_fields,
)
from scripts.run_sync import run_sync
from tests.unit.conftest import CONFIG_DIR

FIELDS = {
    "id": {"type": "data"},
    "first": {"type": "data"},
    "last": {"type": "data"},
    "quantity": {"type": "data", "data_type": "integer"},
    "price": {"type": "data", "data_type": "decimal"},
    "weight": {"type": "data", "data_type": "number"},
    "born": {"type": "data", "data_type": "date"},
    "opened": {"type": "data", "data_type": "date"},
    "closed": {"type": "data", "data_type": "timestamp"},
    "nickname": {"type": "data"},
    "owner": {"type": "link", "target": "Other"},
}


def _type_with(**derived):
    return {"Line": {"id_field": "id", "fields": {
        **FIELDS, **{name: {"type": "data", "derived": formula}
                     for name, formula in derived.items()}}}}


def _derive(formula, **values):
    return compute(derivation_of({"derived": formula}), values, today=date(2026, 10, 13))


class TestTheFormulas:
    def test_concat_skips_empty_inputs_with_their_separator(self):
        formula = {"concat": ["first", "nickname", "last"], "separator": " "}
        assert _derive(formula, first="Ada", nickname=None, last="Okafor") == "Ada Okafor"
        assert _derive(formula, first=None, nickname="", last=None) is None

    @pytest.mark.parametrize("formula, values, expected", [
        ({"add": ["quantity", 2]}, {"quantity": 3}, 5),
        ({"subtract": ["price", "quantity"]}, {"price": Decimal("9.50"), "quantity": 2}, Decimal("7.50")),
        ({"multiply": ["quantity", "price"]}, {"quantity": 3, "price": Decimal("1.10")}, Decimal("3.30")),
        ({"multiply": ["price", 1.2]}, {"price": Decimal("10")}, Decimal("12.0")),
        ({"divide": ["weight", "quantity"]}, {"weight": 7.0, "quantity": 2}, 3.5),
    ])
    def test_arithmetic(self, formula, values, expected):
        assert _derive(formula, **values) == expected

    def test_float_arithmetic_is_exact_to_what_was_typed(self):
        """49.99 x 1.1 is 54.989, not the 54.989000000000004 binary
        floating point makes of it -- which the Browse screen showed."""
        assert _derive({"multiply": ["weight", 1.1]}, weight=49.99) == 54.989
        assert _derive({"add": ["weight", 0.2]}, weight=0.1) == 0.3

    def test_an_empty_input_is_an_empty_result_not_zero(self):
        assert _derive({"multiply": ["quantity", "price"]}, quantity=None, price=Decimal(2)) is None

    def test_dividing_by_zero_is_empty(self):
        assert _derive({"divide": ["weight", "quantity"]}, weight=1.0, quantity=0) is None

    @pytest.mark.parametrize("born, age", [
        (date(2000, 10, 13), 26),   # the birthday itself
        (date(2000, 10, 14), 25),   # tomorrow
        (date(2000, 2, 29), 26),
    ])
    def test_years_since_counts_whole_years(self, born, age):
        assert _derive({"years_since": "born"}, born=born) == age

    def test_days_between_works_across_dates_and_timestamps(self):
        formula = {"days_between": ["opened", "closed"]}
        assert _derive(formula, opened=date(2026, 10, 1), closed=datetime(2026, 10, 13, 23)) == 12

    def test_coalesce_takes_the_first_present(self):
        assert _derive({"coalesce": ["nickname", "first"]}, nickname=None, first="Ada") == "Ada"

    def test_a_decimal_result_is_rounded_to_what_gold_stores(self):
        assert finished(Decimal("1.0000000005"), "decimal") == Decimal("1.000000000")
        assert finished(Decimal("1.0000000015"), "decimal") == Decimal("1.000000002")


class TestTheTypeAFormulaYields:
    @pytest.mark.parametrize("formula, yields", [
        ({"concat": ["first", "last"]}, "string"),
        ({"multiply": ["quantity", 2]}, "integer"),
        ({"multiply": ["quantity", "price"]}, "decimal"),
        ({"multiply": ["quantity", 1.5]}, "number"),
        ({"divide": ["quantity", 2]}, "number"),
        ({"years_since": "born"}, "integer"),
        ({"coalesce": ["nickname", "first"]}, "string"),
    ])
    def test_it(self, formula, yields):
        assert result_type(derivation_of({"derived": formula}), FIELDS) == yields

    def test_it_is_written_into_the_schema_at_load(self):
        schema = _type_with(total={"multiply": ["quantity", "price"]})
        fill_result_types(schema)
        assert schema["Line"]["fields"]["total"]["data_type"] == "decimal"


class TestRefusedAtLoad:
    @pytest.mark.parametrize("formula, says", [
        ({"multiply": ["quantity"]}, "takes 2 input"),
        ({"multiply": ["quantity", "first"]}, "needs numbers"),
        ({"multiply": [2, 3]}, "constant"),
        ({"years_since": "first"}, "needs dates"),
        ({"concat": ["first"]}, "at least two"),
        ({"concat": ["first", 3]}, "field names only"),
        ({"coalesce": ["first", "quantity"]}, "different types"),
        ({"add": ["quantity", "nope"]}, "does not have"),
        ({"add": ["quantity", "owner"]}, "is a link"),
        ({"sum": ["quantity", "price"]}, "exactly one formula"),
        ({"add": ["quantity", 1], "round": 2}, "unknown key"),
        ("quantity * 2", "must name one formula"),
    ])
    def test_a_formula_that_could_never_be_computed(self, formula, says):
        with pytest.raises(ValueError, match=says):
            validate_derived_fields(_type_with(bad=formula))

    def test_a_derived_field_over_a_derived_field(self):
        schema = _type_with(total={"multiply": ["quantity", "price"]})
        schema["Line"]["fields"]["double"] = {"type": "data", "derived": {"multiply": ["total", 2]}}
        with pytest.raises(ValueError, match="itself derived"):
            validate_derived_fields(schema)

    def test_storage_keys_beside_a_formula(self):
        schema = _type_with()
        schema["Line"]["fields"]["total"] = {"type": "data", "column": "total",
                                             "derived": {"multiply": ["quantity", "price"]}}
        with pytest.raises(ValueError, match=r"no stored value; remove \['column'\]"):
            validate_derived_fields(schema)

    def test_a_data_type_that_disagrees_with_the_formula(self):
        schema = _type_with()
        schema["Line"]["fields"]["total"] = {"type": "data", "data_type": "integer",
                                             "derived": {"multiply": ["quantity", "price"]}}
        with pytest.raises(ValueError, match="yields decimal"):
            validate_derived_fields(schema)

    def test_a_cross_field_rule_over_a_derived_field(self):
        schema = _type_with(total={"multiply": ["quantity", "price"]})
        schema["Line"]["rules"] = {"r": {"field": "total", "op": ">=", "other": "price"}}
        with pytest.raises(ValueError, match="derived"):
            refuse_rules_over_derived(schema)


class TestWhoMayReadOne:
    SCHEMA = _type_with(total={"multiply": ["quantity", "price"]})

    def test_a_role_that_cannot_read_an_input_cannot_read_the_result(self):
        roles = {"clerk": {"allowed_actions": frozenset({
            "read:Line.quantity", "read:Line.total"})}}

        gated = gate_derived_grants(roles, self.SCHEMA)

        assert "read:Line.total" not in gated["clerk"]["allowed_actions"]
        assert "discover:Line.total" in gated["clerk"]["allowed_actions"], \
            "it should still show as present-but-hidden"

    def test_a_role_that_can_read_every_input_keeps_it(self):
        roles = {"buyer": {"allowed_actions": frozenset({
            "read:Line.quantity", "read:Line.price", "read:Line.total"})}}

        assert "read:Line.total" in gate_derived_grants(roles, self.SCHEMA)["buyer"]["allowed_actions"]

    def test_nothing_derived_changes_nothing(self):
        roles = {"r": {"allowed_actions": frozenset({"read:Line.quantity"})}}
        assert gate_derived_grants(roles, _type_with()) is roles


def test_gold_s_dict_path_computes_it_too():
    """A fused type publishes through gold._arrow, the others through
    conform_arrow; both end in with_derived, and this is the first."""
    from core.mirror.gold import _arrow

    type_def = {"id_field": "id", "storage": {"id_column": "id"}, "fields": {
        "id": {"type": "data"}, "quantity": {"type": "data", "data_type": "integer"},
        "twice": {"type": "data", "data_type": "integer", "derived": {"multiply": ["quantity", 2]}}}}

    table = _arrow([{"id": "a", "quantity": 4}, {"id": "b", "quantity": None}], type_def)

    assert table.column("twice").to_pylist() == [8, None]
    assert table.schema.field("twice").type == pa.int64()


# -- end to end, through a real sync, gold, and the mediator -------------

ONTOLOGY_ADDITIONS = {
    "Transaction": "      with_fee:\n        derived:\n          multiply: [amount, 1.1]\n",
    "Customer": ("      label:\n        derived:\n          concat: [name, region]\n"
                 "          separator: \" / \"\n"),
}


@pytest.fixture(scope="module")
def deployment(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("derived")
    config_dir = tmp / "etc"
    shutil.copytree(CONFIG_DIR, config_dir)
    ontology = config_dir / "ontology_schema.yaml"
    text = ontology.read_text()
    text = text.replace("      currency:\n        type: data\n",
                        "      currency:\n        type: data\n" + ONTOLOGY_ADDITIONS["Transaction"], 1)
    text = text.replace("      region:\n        type: data\n",
                        "      region:\n        type: data\n" + ONTOLOGY_ADDITIONS["Customer"], 1)
    ontology.write_text(text)
    policy = config_dir / "policy.yaml"
    policy.write_text(policy.read_text().replace(
        "      - read:Transaction.amount\n",
        "      - read:Transaction.amount\n      - read:Transaction.with_fee\n"
        "      - read:Customer.label\n", 1).replace(
        "\nusers:",
        "\n  fee_only:\n    allowed_actions:\n      - read:Transaction\n"
        "      - read:Transaction.transaction_id\n      - read:Transaction.with_fee\n\nusers:", 1))
    paths = RuntimePaths(config_dir=config_dir, data_dir=tmp / "data", log_dir=tmp / "log")
    paths.data_dir.mkdir(parents=True)
    paths.log_dir.mkdir(parents=True)
    for schema_name, db_name in seed.DATABASES:
        seed.build(seed.FIXTURES / schema_name, paths.data_dir / "dev_fixtures" / db_name)
    printed = io.StringIO()
    with contextlib.redirect_stdout(printed):
        assert run_sync(paths) == 0, printed.getvalue()
    config, mediator, _ = load_deployment_bundle(paths.config_dir, paths.data_dir, paths.log_dir)
    return config, mediator


SERVICE = UserRecord("u1", "us-west", "customer_service")
FEE_ONLY = UserRecord("u2", "us-west", "fee_only")


def _a_transaction(mediator):
    ids = mediator.search_object(SERVICE, "Transaction", [])
    assert ids, "the fixture has us-west transactions"
    return ids[0]


class TestThroughARealDeployment:
    def test_a_read_computes_it_from_its_inputs(self, deployment):
        _, mediator = deployment
        tid = _a_transaction(mediator)
        amount = mediator.get_field(SERVICE, "Transaction", tid, "amount")

        assert mediator.get_field(SERVICE, "Transaction", tid, "with_fee") == \
            finished(amount * Decimal("1.1"), "decimal")

    def test_concat_on_a_customer(self, deployment):
        _, mediator = deployment
        assert mediator.get_field(SERVICE, "Customer", "cust_001", "label") == "Ada Okafor / us-west"

    def test_a_change_waiting_to_sync_is_in_the_value_beside_it(self, deployment, monkeypatch):
        """A pending write is served by _read_field_with_log_check -- the
        overlay over gold. A derived value read from gold's stored copy
        would still show the OLD name; computed from its inputs as they
        are read, it shows the new one."""
        _, mediator = deployment
        real = type(mediator)._read_field_with_log_check

        def overlaid(self, object_type, object_id, field_name, *args):
            if (object_type, field_name) == ("Customer", "name"):
                return "Ada Renamed"
            return real(self, object_type, object_id, field_name, *args)

        monkeypatch.setattr(type(mediator), "_read_field_with_log_check", overlaid)

        assert mediator.get_field(SERVICE, "Customer", "cust_001", "label") == "Ada Renamed / us-west"

    def test_the_sync_never_asks_a_source_for_it(self, deployment):
        from core.mirror.sync_targets import resolve_sync_targets

        config, _ = deployment
        columns = {column for target in resolve_sync_targets({"object_types": config.schema})
                   for column in target.columns}
        assert "label" not in columns and "with_fee" not in columns
        assert "name" in columns

    def test_gold_holds_it_so_a_filter_finds_by_it(self, deployment):
        _, mediator = deployment
        tid = _a_transaction(mediator)
        value = mediator.get_field(SERVICE, "Transaction", tid, "with_fee")

        found = mediator.search_object(SERVICE, "Transaction",
                                       [FieldFilter("with_fee", "equals", value)])

        assert tid in found

    def test_a_role_without_an_input_is_refused_the_result(self, deployment):
        """fee_only was GRANTED read:Transaction.with_fee and not amount.
        Reading with_fee would hand them amount times 1.1."""
        _, mediator = deployment
        tid = _a_transaction(mediator)

        assert mediator.get_field(FEE_ONLY, "Transaction", tid, "with_fee") is None
        field = mediator.visible_schema(FEE_ONLY)["Transaction"]["fields"]["with_fee"]
        assert field["readable"] is False

    def test_the_schema_says_how_it_is_computed(self, deployment):
        _, mediator = deployment
        field = mediator.visible_schema(SERVICE)["Transaction"]["fields"]["with_fee"]

        assert field["derived"] == "multiply(amount, 1.1)"
        assert field["data_type"] == "decimal"

    def test_it_cannot_be_written(self, deployment):
        config, mediator = deployment
        from core.ontology.write_mediator import WriteMediator

        with pytest.raises(ValueError, match="derived from other fields"):
            WriteMediator._group_changes_by_storage(
                type("W", (), {"_adapter_mediator": mediator})(), "Transaction",
                {"with_fee": Decimal(1)})


def test_an_action_that_sets_a_derived_field_is_refused_at_load(tmp_path):
    config_dir = tmp_path / "etc"
    shutil.copytree(CONFIG_DIR, config_dir)
    ontology = config_dir / "ontology_schema.yaml"
    ontology.write_text(ontology.read_text()
                        .replace("      currency:\n        type: data\n",
                                 "      currency:\n        type: data\n"
                                 + ONTOLOGY_ADDITIONS["Transaction"], 1)
                        .replace("              property: category", "              property: with_fee", 1))

    with pytest.raises(ValueError, match="derived from other fields"):
        load_deployment_bundle(config_dir, tmp_path / "data", tmp_path / "log", serving=False)


def test_the_data_contract_says_how_it_is_computed_and_stays_valid_odcs(deployment):
    """ODCS v3 has `transformLogic` on a property for exactly this; the
    contract must still validate against the standard's own schema."""
    from core.mirror.data_contracts import data_contract
    from tests.unit.test_data_contracts import _valid

    config, _ = deployment
    contract = data_contract("Transaction", config.schema)
    (with_fee,) = [prop for prop in contract["schema"][0]["properties"] if prop["name"] == "with_fee"]

    assert with_fee["transformLogic"] == "multiply(amount, 1.1)"
    _valid(contract)
