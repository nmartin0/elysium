"""
Tests for multi-datasource object types (MDO) -- one object type whose
DIFFERENT properties are backed by genuinely different silos, joined
on a shared identity value. Matches Palantir Foundry's own column-wise
MDO concept (see core/ontology/mediator.py's _resolve_shared_storage()
docstring for the full architectural reasoning and this project's
deliberate v1 scope boundary).

TEST_SCHEMA deliberately exercises the two real-world mismatches MDO
exists to handle, not just "two silos, same naming convention":
  - risk_db's OWN id_column is "cust_ref", not "customer_id" -- MDO
    assumes the IDENTITY VALUE is shared across silos, never that the
    ID COLUMN NAME is.
  - risk_score's OWN column in risk_db is "score_val", not
    "risk_score" -- the column-name override (get_field_column()),
    folded into this same schema surface since a real external silo
    won't always happen to name its columns like our own field names.

alice: region us-west, full grants including BOTH storages
dave: region us-west, grants Customer.name but NOT Customer.risk_score
      -- for the field-level-RBAC-still-applies-per-MDO-field test
"""

import sqlite3

import pytest

from core.deployment_loader import _build_adapters
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_mediator import WriteMediator

TEST_SCHEMA = {
    "Customer": {
        "storage": {"silo": "primary_sql", "table": "customers", "id_column": "customer_id"},
        "additional_storage": {
            "risk_db": {"silo": "risk_sql", "table": "customer_risk", "id_column": "cust_ref"},
        },
        "id_field": "customer_id",
        "security": {"field": "region"},
        "fields": {
            "region": {"type": "data"},
            "name": {"type": "data"},
            "risk_score": {"type": "data", "storage": "risk_db", "column": "score_val"},
        },
    },
}

TEST_ROLES = {
    "full": {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name", "read:Customer.risk_score",
        "write:Customer.risk_score", "write:Customer.name",
    ]},
    "name_only": {"allowed_actions": ["read:Customer", "read:Customer.customer_id", "read:Customer.name"]},
}

TEST_USERS = {
    "alice": {"region": "us-west", "role": "full"},
    "dave": {"region": "us-west", "role": "name_only"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def mediator(tmp_path):
    db_primary = tmp_path / "primary.db"
    conn = sqlite3.connect(db_primary)
    conn.executescript("""
        CREATE TABLE customers (customer_id TEXT PRIMARY KEY, region TEXT, name TEXT);
        INSERT INTO customers VALUES ('cust_001', 'us-west', 'Ada Okafor');
    """)
    conn.commit()
    conn.close()

    db_risk = tmp_path / "risk.db"
    conn = sqlite3.connect(db_risk)
    conn.executescript("""
        CREATE TABLE customer_risk (cust_ref TEXT PRIMARY KEY, score_val REAL);
        INSERT INTO customer_risk VALUES ('cust_001', 0.42);
    """)
    conn.commit()
    conn.close()

    adapters = _build_adapters({
        "primary_sql": {"adapter": "sqlite", "connection": {"path": db_primary}},
        "risk_sql": {"adapter": "sqlite", "connection": {"path": db_risk}},
    })
    silo_for_type = {"Customer": "primary_sql"}
    return DataMediator(TEST_SCHEMA, adapters, silo_for_type, TEST_ROLES)


def test_reads_a_primary_storage_field_normally(mediator):
    assert mediator.get_field(_record("alice"), "Customer", "cust_001", "name") == "Ada Okafor"


def test_reads_an_mdo_field_from_a_genuinely_different_silo(mediator):
    # Different silo, different id_column name (cust_ref vs
    # customer_id), different column name (score_val vs risk_score) --
    # all three mismatches resolved correctly in one call.
    assert mediator.get_field(_record("alice"), "Customer", "cust_001", "risk_score") == 0.42


def test_field_level_rbac_still_applies_independently_per_mdo_field(mediator):
    # dave can see name (primary storage) but NOT risk_score (MDO,
    # risk_db) -- MDO doesn't create a new security concept; the
    # existing per-field RBAC gate just needs to keep working correctly
    # once fields can come from different places.
    dave = _record("dave")
    assert mediator.get_field(dave, "Customer", "cust_001", "name") == "Ada Okafor"
    assert mediator.get_field(dave, "Customer", "cust_001", "risk_score") is None


def test_search_by_a_primary_field_still_works(mediator):
    assert mediator.search_object(_record("alice"), "Customer", {"name": "Ada Okafor"}) == ["cust_001"]


def test_search_by_an_mdo_field_resolves_to_the_right_silo(mediator):
    assert mediator.search_object(_record("alice"), "Customer", {"risk_score": 0.42}) == ["cust_001"]


def test_search_mixing_fields_from_different_storages_is_rejected(mediator):
    # THE v1 scope boundary for reads -- a single search filter may
    # only touch ONE storage at a time. Federated intersection across
    # storages is real, unsolved territory, deliberately out of scope.
    with pytest.raises(ValueError, match="cannot combine fields from multiple storages"):
        mediator.search_object(_record("alice"), "Customer", {"name": "Ada Okafor", "risk_score": 0.42})


def test_write_to_an_mdo_field_actually_changes_the_right_database(mediator):
    write_mediator = WriteMediator(mediator, TEST_ROLES)
    alice = _record("alice")

    pending = write_mediator.propose_write(alice, "Customer", "cust_001", "update", {"risk_score": 0.99})
    assert pending.expected_current_values == {"risk_score": 0.42}

    outcome = write_mediator.confirm_and_execute(pending, approved=True)
    assert outcome == {"status": "written", "object_id": "cust_001"}
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.99

    # And the PRIMARY storage's own field is provably untouched --
    # proof the write genuinely only reached risk_db, not primary_sql.
    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "Ada Okafor"


def test_write_mixing_fields_from_different_storages_is_rejected(mediator):
    # THE v1 scope boundary for writes -- no atomicity guarantee exists
    # across genuinely separate databases, so this is rejected outright
    # rather than silently attempted as two non-atomic writes.
    write_mediator = WriteMediator(mediator, TEST_ROLES)
    alice = _record("alice")
    with pytest.raises(ValueError, match="cannot combine fields from multiple storages"):
        write_mediator.propose_write(alice, "Customer", "cust_001", "update",
                                      {"name": "New Name", "risk_score": 0.5})


def test_search_with_empty_criteria_defaults_to_primary_storage(mediator):
    # No fields specified at all -- "give me everything" -- must not
    # crash trying to resolve a shared storage across zero fields; the
    # primary storage is the only sensible default.
    result = mediator.search_object(_record("alice"), "Customer", {})
    assert result == ["cust_001"]
