"""
Tests proving links CAN cross data-silo boundaries -- a security chain
(via_field) and a reverse link (cardinality: many) can both correctly
resolve when the source and target object types live in genuinely
separate databases, not just separate tables within one database.

This corrects an earlier, overly-cautious design: core/ontology/
mediator.py used to unconditionally reject ANY cross-silo link
traversal via an _assert_same_silo() guard. Investigating this
surfaced two DIFFERENT situations, not one:

  - The security-chain (via_field) path was ALREADY mechanically
    correct across silos -- _get_security_value()'s recursive call
    re-resolves _adapter_for(target_type) fresh from that type's OWN
    silo declaration, at every hop. The guard here was blocking
    something that already worked; removing it is the whole fix.

  - The reverse-link (cardinality: many) path had a REAL bug: it
    resolved the via_table query against the SOURCE type's adapter,
    but a reverse link's via_table almost always physically lives in
    the TARGET type's own database. This raised "no such table" the
    moment source and target were in different silos. The actual fix
    is using the TARGET's adapter, not just removing the guard.

Deliberately NOT testing a cross-silo FORWARD link (cardinality: one)
separately -- that path never touched the guard at all (it's just
reading a plain column value), so there was nothing to fix there; the
"authorized user reads correctly" test below exercises it anyway as
part of the natural flow (following employee_id back to Employee).
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.deployment_loader import _build_adapters
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator

TEST_SCHEMA = {
    "Employee": {
        "silo": "silo_a", "id_field": "employee_id", "table": "employees", "id_column": "employee_id",
        "security": {"field": "department"},
        "fields": {
            "department": {"type": "data"},
            "full_name": {"type": "data"},
            "payroll_records": {
                "type": "link", "target": "PayrollRecord", "cardinality": "many",
                "via_table": "payroll_records", "via_column": "employee_id",
            },
        },
    },
    "PayrollRecord": {
        "silo": "silo_b", "id_field": "record_id", "table": "payroll_records", "id_column": "record_id",
        # MAC boundary genuinely CROSSES from silo_b into silo_a here.
        "security": {"via_field": "employee_id"},
        "fields": {
            "salary": {"type": "data"},
            "employee_id": {"type": "link", "target": "Employee", "cardinality": "one"},
        },
    },
}

TEST_ROLES = {
    "r": {"allowed_actions": [
        "read:Employee", "read:Employee.employee_id", "read:Employee.payroll_records",
        "read:PayrollRecord", "read:PayrollRecord.salary", "read:PayrollRecord.employee_id",
    ]},
}


@pytest.fixture
def mediator(tmp_path):
    # Employee lives in db_a; PayrollRecord (including the via_table
    # for the reverse link) lives in a COMPLETELY SEPARATE db_b.
    db_a = tmp_path / "db_a.db"
    conn = sqlite3.connect(db_a)
    conn.executescript("""
        CREATE TABLE employees (employee_id TEXT PRIMARY KEY, department TEXT, full_name TEXT);
        INSERT INTO employees VALUES ('emp_001', 'engineering', 'Alice Chen');
    """)
    conn.commit()
    conn.close()

    db_b = tmp_path / "db_b.db"
    conn = sqlite3.connect(db_b)
    conn.executescript("""
        CREATE TABLE payroll_records (record_id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT, salary REAL);
        INSERT INTO payroll_records (employee_id, salary) VALUES ('emp_001', 95000.0), ('emp_001', 12000.0);
    """)
    conn.commit()
    conn.close()

    adapters = _build_adapters({
        "silo_a": {"adapter": "sqlite", "connection": {"path": db_a}},
        "silo_b": {"adapter": "sqlite", "connection": {"path": db_b}},
    })
    silo_for_type = {"Employee": "silo_a", "PayrollRecord": "silo_b"}
    return DataMediator(TEST_SCHEMA, adapters, silo_for_type, TEST_ROLES)


def test_cross_silo_reverse_link_resolves_correctly(mediator):
    users = {"alice": {"department": "engineering", "role": "r"}}
    alice = resolve_user_record(users, "alice", "department")

    records = mediator.get_field(alice, "Employee", "emp_001", "payroll_records")
    assert set(records) == {1, 2}


def test_cross_silo_mac_security_chain_allows_matching_department(mediator):
    users = {"alice": {"department": "engineering", "role": "r"}}
    alice = resolve_user_record(users, "alice", "department")

    salary = mediator.get_field(alice, "PayrollRecord", 1, "salary")
    assert salary == 95000.0


def test_cross_silo_mac_security_chain_blocks_mismatched_department(mediator):
    # The MAC boundary must still hold correctly even though resolving
    # it now means a genuine cross-database lookup -- crossing a silo
    # boundary must never accidentally weaken enforcement.
    users = {"bob": {"department": "hr", "role": "r"}}
    bob = resolve_user_record(users, "bob", "department")

    salary = mediator.get_field(bob, "PayrollRecord", 1, "salary")
    assert salary is None


def test_full_traversal_chain_across_both_silos(mediator):
    # Employee (silo_a) -> reverse link -> PayrollRecord (silo_b) ->
    # forward link back -> Employee (silo_a) again. Every hop resolves
    # its own adapter independently and correctly.
    users = {"alice": {"department": "engineering", "role": "r"}}
    alice = resolve_user_record(users, "alice", "department")

    record_ids = mediator.get_field(alice, "Employee", "emp_001", "payroll_records")
    first_record_id = sorted(record_ids)[0]
    salary = mediator.get_field(alice, "PayrollRecord", first_record_id, "salary")
    back_to_employee = mediator.get_field(alice, "PayrollRecord", first_record_id, "employee_id")

    assert salary in (95000.0, 12000.0)
    assert back_to_employee == "emp_001"
