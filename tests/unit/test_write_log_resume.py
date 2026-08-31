"""
Tests for WriteMediator.resume_pending_writes() -- the startup-time
crash-recovery half of the write-log mechanism (see write_log.py's own
module docstring for why this was deferred out of the first increment,
and resume_pending_writes()'s own docstring for the full reconciliation
logic this proves).

THE KEY CORRECTNESS PROPERTY under test throughout: resume must NEVER
blindly re-run write_fields() for every group in a pending entry --
that would incorrectly treat an ALREADY-applied group as a fresh
failure, since its real value no longer matches the OLD
expected_current_values a conditional write checks against, precisely
BECAUSE it already succeeded. Every test here constructs a pending
log entry directly (bypassing confirm_and_execute() entirely, via
write_log.log_pending_update()) so the real backend's OWN state --
fully unapplied, partially applied, or genuinely ambiguous -- can be
set up exactly, rather than relying on interrupting a real apply
mid-sequence.

Reuses test_write_log.py's own MDO Customer schema/fixture shape
deliberately, for the same reason that file does: risk_db's own
id_column (cust_ref, not customer_id) and column name (score_val, not
risk_score) are real mismatches worth exercising, not just "two
storages, same naming convention."

alice: region us-west, full grants across both storages.
"""

import sqlite3

import pytest

from core.deployment_loader import _build_adapters
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLog
from core.ontology.write_mediator import WriteMediator
from tests.conftest import read_audit_log

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
    ]},
}

TEST_USERS = {
    "alice": {"region": "us-west", "role": "full"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def fixture(tmp_path, isolated_audit_log):
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
    audit_log = AuditLog(isolated_audit_log / "audit.log")

    adapters = _build_adapters({
        "primary_sql": {"adapter": "sqlite", "connection": {"path": db_primary}},
        "risk_sql": {"adapter": "sqlite", "connection": {"path": db_risk}},
    })
    mediator = DataMediator(TEST_SCHEMA, adapters, {"Customer": "primary_sql"}, TEST_ROLES,
                             write_log=write_log, audit_log=audit_log)
    write_mediator = WriteMediator(mediator, TEST_ROLES, {})
    return mediator, write_mediator, write_log


def _direct_write(mediator, silo, table, id_column, id_value, column, value):
    # Bypasses the write log ENTIRELY -- simulates "this group's write
    # already committed to the real backend before the crash," or
    # "something external touched this field," depending on the test.
    adapter = mediator.adapters[silo]
    with adapter._connection() as conn:
        conn.execute(f"UPDATE {table} SET {column} = ? WHERE {id_column} = ?", (value, id_value))
        conn.commit()


def test_resume_with_nothing_pending_is_a_clean_noop(fixture):
    mediator, write_mediator, _ = fixture
    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 0, "already_applied": 0, "ambiguous": 0}


def test_resume_completes_a_write_that_never_applied(fixture):
    # Simulates the cleanest crash: the log entry was written, but the
    # process died before EITHER storage group's write_fields() call
    # ever ran -- both groups still hold their original, pre-write values.
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        "Customer", "cust_001",
        {"name": "New Name", "risk_score": 0.99}, {"name": "Ada Okafor", "risk_score": 0.42},
        "alice", "simulated crash before any group applied",
    )

    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 1, "already_applied": 0, "ambiguous": 0}

    # Both storages now hold the intended values...
    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "New Name"
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.99
    # ...and the log entry is genuinely resolved, not just masking via
    # the read-merge -- get_field() would show the SAME values even if
    # the log were wiped entirely.
    assert write_log.get_pending_changes("Customer", "cust_001") is None


def test_resume_skips_already_applied_group_and_completes_the_other(fixture):
    # THE key correctness property -- see module docstring. Simulates
    # "crashed AFTER the primary-storage group committed, BEFORE the
    # MDO group did": name is already "New Name" for real; risk_score
    # is still its old, pre-write value. A naive resume that just
    # re-ran write_fields() for BOTH groups would incorrectly treat the
    # name group as a failure (its real value no longer matches the
    # OLD expected_current_values the conditional write checks against).
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        "Customer", "cust_001",
        {"name": "New Name", "risk_score": 0.99}, {"name": "Ada Okafor", "risk_score": 0.42},
        "alice", "simulated crash after primary group applied, before MDO group",
    )
    # Simulate: the primary-storage group's write already, genuinely
    # committed before the crash.
    _direct_write(mediator, "primary_sql", "customers", "customer_id", "cust_001", "name", "New Name")

    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 1, "already_applied": 0, "ambiguous": 0}

    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "New Name"
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.99
    assert write_log.get_pending_changes("Customer", "cust_001") is None


def test_resume_when_every_group_already_applied(fixture):
    # The OTHER clean case: the crash happened AFTER every group's
    # write already committed, but BEFORE mark_applied() ran. Resume
    # should recognize this and simply close the entry out -- no group
    # gets a redundant write_fields() call.
    mediator, write_mediator, write_log = fixture

    write_log.log_pending_update(
        "Customer", "cust_001",
        {"name": "New Name", "risk_score": 0.99}, {"name": "Ada Okafor", "risk_score": 0.42},
        "alice", "simulated crash after both groups applied, before mark_applied",
    )
    _direct_write(mediator, "primary_sql", "customers", "customer_id", "cust_001", "name", "New Name")
    _direct_write(mediator, "risk_sql", "customer_risk", "cust_ref", "cust_001", "score_val", 0.99)

    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 0, "already_applied": 1, "ambiguous": 0}
    assert write_log.get_pending_changes("Customer", "cust_001") is None


def test_resume_leaves_ambiguous_entry_pending_and_logs(fixture, isolated_audit_log):
    # The backend holds NEITHER the old nor the new value for
    # risk_score -- something else touched it between the crash and
    # recovery. Resume must NOT guess by overwriting either way.
    mediator, write_mediator, write_log = fixture

    write_log.log_pending_update(
        "Customer", "cust_001",
        {"name": "New Name", "risk_score": 0.99}, {"name": "Ada Okafor", "risk_score": 0.42},
        "alice", "simulated external interference on risk_score",
    )
    _direct_write(mediator, "primary_sql", "customers", "customer_id", "cust_001", "name", "New Name")
    # Neither 0.42 (old) nor 0.99 (new) -- a third, unexpected value.
    _direct_write(mediator, "risk_sql", "customer_risk", "cust_ref", "cust_001", "score_val", 0.77)

    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 0, "already_applied": 0, "ambiguous": 1}

    # The entry stays pending -- get_field() still defers to the log's
    # OWN intended value for risk_score (the same safe, degraded state
    # as before recovery ran), and the real, unexpected 0.77 is left
    # completely untouched, not silently overwritten either direction.
    assert write_log.get_pending_changes("Customer", "cust_001") == {
        "name": "New Name", "risk_score": 0.99
    }
    real_adapter = mediator.adapters["risk_sql"]
    raw_value = real_adapter.get_raw_field("Customer", "cust_001", "score_val",
                                            {"storage": {"table": "customer_risk", "id_column": "cust_ref"}})
    assert raw_value == 0.77, "the real, ambiguous value must be left untouched"

    entries = read_audit_log(isolated_audit_log)
    ambiguous_entries = [e for e in entries if e["stage"] == "write_resume_ambiguous"]
    assert len(ambiguous_entries) == 1
    assert ambiguous_entries[0]["field_name"] == "risk_score"
    assert ambiguous_entries[0]["current_value"] == 0.77
    assert ambiguous_entries[0]["expected_old_value"] == 0.42
    assert ambiguous_entries[0]["expected_new_value"] == 0.99


def test_resume_is_idempotent(fixture):
    mediator, write_mediator, write_log = fixture

    write_log.log_pending_update(
        "Customer", "cust_001",
        {"risk_score": 0.99}, {"risk_score": 0.42}, "alice", "test",
    )

    first = write_mediator.resume_pending_writes()
    assert first == {"resumed": 1, "already_applied": 0, "ambiguous": 0}

    second = write_mediator.resume_pending_writes()
    assert second == {"resumed": 0, "already_applied": 0, "ambiguous": 0}


def test_resume_handles_a_single_storage_entry(fixture):
    # Not every pending entry spans multiple storages -- the common,
    # single-group case must resume correctly too, not just the MDO one.
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        "Customer", "cust_001",
        {"risk_score": 0.55}, {"risk_score": 0.42}, "alice", "single-storage crash",
    )

    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 1, "already_applied": 0, "ambiguous": 0}
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.55
