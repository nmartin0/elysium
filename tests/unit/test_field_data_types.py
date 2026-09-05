"""
Tests for core/ontology/field_types.py and the typed mirror sync it
enables -- the fix for the type-fidelity blocker Phase 4's own
side-by-side verification surfaced (Account.balance reading as 900.0
live but '500.0' from the mirror).

The central property, and the one that actually made the blocker
real: a field's value must have the SAME Python type whether it is
read live or from the mirror. Everything else here supports that.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.mirror_adapter import MirrorReadAdapter
from core.mirror.sync_targets import resolve_sync_targets
from core.ontology.field_types import DEFAULT_FIELD_DATA_TYPE, arrow_type_for, coerce
from core.ontology.object_type_validation import validate_object_types


def test_coerce_returns_real_types_not_strings():
    assert coerce("500.0", "number") == 500.0
    assert isinstance(coerce("500.0", "number"), float)
    assert coerce("42", "integer") == 42
    assert isinstance(coerce("42", "integer"), int)
    assert coerce(500.0, "string") == "500.0"


def test_coerce_leaves_none_alone():
    # A real NULL is not a type error -- it stays NULL for every type.
    for data_type in ("string", "integer", "number", "boolean"):
        assert coerce(None, data_type) is None


def test_coerce_handles_sqlite_booleans_correctly():
    # SQLite has no real boolean -- it stores 0/1. A plain bool() on
    # the STRING "0" would be True (non-empty strings are truthy),
    # which would be a real, silent bug.
    assert coerce("0", "boolean") is False
    assert coerce("1", "boolean") is True
    assert coerce(0, "boolean") is False
    assert coerce(1, "boolean") is True


def test_coerce_raises_on_a_genuine_mismatch_rather_than_substituting():
    # An ontology/source disagreement must surface loudly, not become a
    # wrong value in the mirror.
    with pytest.raises(ValueError):
        coerce("not a number", "integer")


def test_an_unknown_data_type_raises_rather_than_defaulting():
    with pytest.raises(ValueError, match="Unknown field data_type"):
        arrow_type_for("nonexistent_type")


def test_the_default_is_string_so_untyped_schemas_keep_working():
    assert DEFAULT_FIELD_DATA_TYPE == "string"


def test_validation_rejects_an_unknown_declared_data_type():
    # A typo must fail at deployment load, not later inside a
    # scheduled sync far from the schema that caused it.
    schema = {
        "Widget": {
            "storage": {"silo": "primary", "table": "widgets", "id_column": "widget_id"},
            "id_field": "widget_id",
            "security": {"field": "region"},
            "fields": {
                "region": {"type": "data"},
                "size": {"type": "data", "data_type": "flotaing_point"},
            },
        }
    }
    with pytest.raises(ValueError, match="unknown data_type"):
        validate_object_types(schema)


def test_validation_rejects_a_data_type_on_a_link_field():
    # A link's value is an id resolved from the TARGET type -- its type
    # is that target's business, not this field's to redeclare.
    schema = {
        "Widget": {
            "storage": {"silo": "primary", "table": "widgets", "id_column": "widget_id"},
            "id_field": "widget_id",
            "security": {"field": "region"},
            "fields": {
                "region": {"type": "data"},
                "owner": {"type": "link", "target": "Person", "cardinality": "one", "data_type": "string"},
            },
        }
    }
    with pytest.raises(ValueError, match="must not"):
        validate_object_types(schema)


def test_a_schema_declaring_no_data_types_still_validates():
    # Every deployment predating this feature must stay valid.
    schema = {
        "Widget": {
            "storage": {"silo": "primary", "table": "widgets", "id_column": "widget_id"},
            "id_field": "widget_id",
            "security": {"field": "region"},
            "fields": {"region": {"type": "data"}, "name": {"type": "data"}},
        }
    }
    validate_object_types(schema)  # does not raise


def test_sync_targets_carry_the_declared_types():
    schema = {
        "object_types": {
            "Account": {
                "storage": {"silo": "primary", "table": "accounts", "id_column": "account_id"},
                "id_field": "account_id",
                "fields": {
                    "balance": {"type": "data", "data_type": "number"},
                    "currency": {"type": "data"},
                },
            }
        }
    }
    target = resolve_sync_targets(schema)[0]

    assert target.column_types == {"balance": "number"}
    # An undeclared column is simply absent -- it takes the default.
    assert "currency" not in target.column_types


@pytest.fixture
def typed_source(tmp_path):
    path = tmp_path / "biz.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE accounts (account_id TEXT PRIMARY KEY, balance REAL, label TEXT)")
    conn.executemany(
        "INSERT INTO accounts VALUES (?, ?, ?)",
        [("acc_1", 500.0, "checking"), ("acc_2", 1000.0, "savings")],
    )
    conn.commit()
    conn.close()
    return path


def test_a_declared_number_survives_the_mirror_round_trip_as_a_float(tmp_path, typed_source):
    # THE regression test for the real blocker: same field, same value,
    # same Python type from both paths.
    live = SQLiteReadAdapter({"path": typed_source})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": live})
    sync.sync_table(
        "primary", "accounts", "account_id",
        ["account_id", "balance", "label"],
        {"balance": "number"},
    )
    mirror = MirrorReadAdapter(sync._catalog, "primary")

    config = {"storage": {"table": "accounts", "id_column": "account_id"}}
    live_value = live.get_raw_field("Account", "acc_1", "balance", config)
    mirror_value = mirror.get_raw_field("Account", "acc_1", "balance", config)

    assert mirror_value == live_value
    assert isinstance(mirror_value, float)
    assert type(mirror_value) is type(live_value)


def test_an_undeclared_column_still_mirrors_as_a_string(tmp_path, typed_source):
    # The default path, unchanged -- proving the feature is genuinely
    # additive rather than altering existing behavior.
    live = SQLiteReadAdapter({"path": typed_source})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": live})
    sync.sync_table("primary", "accounts", "account_id", ["account_id", "label"], {})
    mirror = MirrorReadAdapter(sync._catalog, "primary")

    config = {"storage": {"table": "accounts", "id_column": "account_id"}}
    assert mirror.get_raw_field("Account", "acc_1", "label", config) == "checking"


def test_filtering_on_a_typed_column_still_works(tmp_path, typed_source):
    # Criteria are stringified before comparison, so a genuinely typed
    # column must still be filterable -- otherwise typing the mirror
    # would silently break search.
    live = SQLiteReadAdapter({"path": typed_source})
    sync = IcebergMirrorSync(tmp_path / "mirror", {"primary": live})
    sync.sync_table(
        "primary", "accounts", "account_id",
        ["account_id", "balance", "label"],
        {"balance": "number"},
    )
    mirror = MirrorReadAdapter(sync._catalog, "primary")

    config = {"storage": {"table": "accounts", "id_column": "account_id"}}
    assert mirror.find_ids("Account", {"label": "checking"}, config) == ["acc_1"]
