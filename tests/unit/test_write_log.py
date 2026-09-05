"""
Tests for core/ontology/write_log.py's atomicity mechanism -- proves
the NEW capability directly: an "update" whose mutations touch fields
on genuinely DIFFERENT storages (MDO's column-wise case) now succeeds,
rather than being rejected outright, when write_log is configured. See
write_log.py's own module docstring for the full mechanism and its
current, deliberate scope boundary (update only; "create," crash
recovery, and search_object() integration all explicitly deferred).

Deliberately a SEPARATE fixture from tests/unit/test_mdo.py, not a
reuse of it -- this one threads write_log through both DataMediator
and WriteMediator, which test_mdo.py's fixture does NOT do on purpose:
test_mdo.py's own test_action_mixing_fields_from_
different_storages_is_rejected specifically proves the ORIGINAL,
direct-write fallback still correctly rejects multi-storage writes
when no write_log is configured -- that test's correctness
depends on this file's new capability NOT leaking into it.

alice: region us-west, full grants across both storages -- same
       shape as test_mdo.py's own alice, kept separate deliberately.
"""

import sqlite3

import pytest

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLog
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
        "execute:UpdateNameAndRiskScore", "execute:UpdateRiskScore",
    ]},
}

TEST_ACTION_TYPES = {
    "UpdateNameAndRiskScore": {
        "affected_object_types": ["Customer"],
        "parameters": {
            "customer_id": {"type": "object_reference", "object_type": "Customer", "required": True},
            "new_name": {"type": "string", "required": True},
            "new_score": {"type": "number", "required": True},
        },
        "sub_writes": [{
            "object_type": "Customer",
            "object_id": "parameter.customer_id",
            "operation": "update",
            "mutations": [
                {"set": {"property": "name", "value": "parameter.new_name"}},
                {"set": {"property": "risk_score", "value": "parameter.new_score"}},
            ],
        }],
    },
    "UpdateRiskScore": {
        "affected_object_types": ["Customer"],
        "parameters": {
            "customer_id": {"type": "object_reference", "object_type": "Customer", "required": True},
            "new_score": {"type": "number", "required": True},
        },
        "sub_writes": [{
            "object_type": "Customer",
            "object_id": "parameter.customer_id",
            "operation": "update",
            "mutations": [{"set": {"property": "risk_score", "value": "parameter.new_score"}}],
        }],
    },
}

TEST_USERS = {
    "alice": {"region": "us-west", "role": "full"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def fixture(tmp_path):
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

    write_log = WriteLog(tmp_path / "write_log.db")

    adapters = _build_adapters({
        "primary_sql": {"adapter": "sqlite", "connection": {"path": db_primary}},
        "risk_sql": {"adapter": "sqlite", "connection": {"path": db_risk}},
    }, _WRITE_ADAPTER_REGISTRY)
    mediator = DataMediator(TEST_SCHEMA, adapters, {"Customer": "primary_sql"}, TEST_ROLES, write_log=write_log)
    write_mediator = WriteMediator(mediator, adapters, TEST_ROLES, TEST_ACTION_TYPES)
    return mediator, write_mediator, write_log


def test_multi_storage_update_succeeds_via_the_log(fixture):
    # THE core, positive proof: an update touching BOTH primary_sql
    # (name) and risk_db (risk_score) is no longer rejected outright
    # -- it succeeds, and BOTH storages genuinely, independently
    # change.
    mediator, write_mediator, _ = fixture
    alice = _record("alice")

    pending = write_mediator.propose_action(
        alice, "UpdateNameAndRiskScore",
        {"customer_id": "cust_001", "new_name": "New Name", "new_score": 0.99},
    )
    outcome = write_mediator.confirm_and_execute(pending, approved=True)

    assert outcome == {"status": "written", "object_ids": ["cust_001"]}
    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "New Name"
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.99


def test_single_storage_update_still_works_via_the_log_path(fixture):
    # The common case (one storage) must keep working correctly when
    # write_log IS configured, not just the multi-storage case
    # -- _group_changes_by_storage() should produce exactly one group
    # here, and the whole flow should behave identically to before.
    mediator, write_mediator, _ = fixture
    alice = _record("alice")

    pending = write_mediator.propose_action(alice, "UpdateRiskScore", {"customer_id": "cust_001", "new_score": 0.77})
    outcome = write_mediator.confirm_and_execute(pending, approved=True)

    assert outcome == {"status": "written", "object_ids": ["cust_001"]}
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.77
    # And the field on the OTHER storage is provably untouched.
    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "Ada Okafor"


def test_read_during_pending_window_sees_the_intended_value(fixture):
    # Proves the read-merge mechanism directly, without relying on
    # timing: manually logs an entry (simulating "mid-apply," as if
    # the process had been interrupted between the two storage
    # groups' own writes), then confirms get_field() returns the
    # LOGGED, intended value for a field that has NOT actually been
    # written to its real backend yet at all.
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        "Customer", "cust_001",
        {"risk_score": 0.55}, {"risk_score": 0.42}, "alice", "simulated in-flight update",
    )

    # The REAL backend still has the OLD value -- proves this isn't
    # accidentally passing because the real write already happened.
    real_adapter = mediator.adapters["risk_sql"]
    raw_value = real_adapter.get_raw_field("Customer", "cust_001", "score_val",
                                            {"storage": {"table": "customer_risk", "id_column": "cust_ref"}})
    assert raw_value == 0.42, "the real backend should NOT have changed yet"

    # But a read through the mediator sees the PENDING, intended value.
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.55


def test_read_after_apply_no_longer_consults_the_log(fixture):
    # After a full, successful confirm_and_execute(), the log entry is
    # marked applied -- a subsequent read must reflect the REAL
    # backend, not linger on the log at all.
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    pending = write_mediator.propose_action(alice, "UpdateRiskScore", {"customer_id": "cust_001", "new_score": 0.88})
    write_mediator.confirm_and_execute(pending, approved=True)

    assert write_log.get_pending_changes("Customer", "cust_001") is None
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.88


def test_expected_current_values_lost_update_check_still_works(fixture):
    # The lost-update protection (expected_current_values mismatch)
    # must still correctly raise through the NEW log-based path, not
    # just the original direct-write one.
    mediator, write_mediator, _ = fixture
    alice = _record("alice")

    pending = write_mediator.propose_action(alice, "UpdateRiskScore", {"customer_id": "cust_001", "new_score": 0.99})
    # Simulate a concurrent change to the SAME field between proposal
    # and confirmation, directly against the real backend.
    real_adapter = mediator.adapters["risk_sql"]
    real_adapter.write_fields("Customer", "cust_001", {"score_val": 0.11}, {"score_val": 0.42},
                               {"storage": {"table": "customer_risk", "id_column": "cust_ref"}})

    with pytest.raises(ValueError, match="changed since this write was proposed"):
        write_mediator.confirm_and_execute(pending, approved=True)


def test_log_entry_marked_applied_not_left_pending(fixture):
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    pending = write_mediator.propose_action(
        alice, "UpdateNameAndRiskScore",
        {"customer_id": "cust_001", "new_name": "Another Name", "new_score": 0.33},
    )
    write_mediator.confirm_and_execute(pending, approved=True)

    assert write_log.get_pending_changes("Customer", "cust_001") is None
