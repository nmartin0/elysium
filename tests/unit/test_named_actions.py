"""
Tests for WriteMediator.propose_action() -- the named-action-types
write path, matching Palantir Foundry's own action-type model
directly: a NAMED, independently-governed operation with its own
execute: grant, declared parameters, and declared mutations -- not a
generic CRUD verb with free-form field input. See
core/ontology/write_mediator.py's module docstring for the full
reasoning.

TEST_ACTION_TYPES deliberately exercises the full mechanism, not a
simplified version: a "current_state" submission criterion (the ticket
must currently be closed), a REQUIRED parameter, a mutation that's a
LITERAL value and one that's a "parameter.<name>" reference -- and
"reopen_reason" starts genuinely NULL in the fixture, specifically to
prove the real NULL-comparison fix in adapters/sqlite_adapter.py (see
tests/unit/test_sqlite_adapter_write_fields.py for the dedicated,
lower-level regression test) actually holds through the full
WriteMediator path, not just at the adapter level in isolation.

lead: region us-west, execute:ReopenTicket + full read grants
nobody: region us-west, NO role at all -- RBAC denial test
wrong_region: region us-east, execute:ReopenTicket granted -- MAC
              denial test, proving action-level RBAC doesn't bypass MAC
"""

import sqlite3

import pytest

from core.deployment_loader import _build_adapters
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_mediator import WriteMediator
from core.ontology.submission_criteria import SubmissionCriteriaViolation

TEST_SCHEMA = {
    "Ticket": {
        "storage": {"silo": "primary", "table": "tickets", "id_column": "ticket_id"},
        "id_field": "ticket_id",
        "security": {"field": "region"},
        "fields": {
            "region": {"type": "data"},
            "status": {"type": "data"},
            "reopen_reason": {"type": "data"},
        },
    },
}

TEST_ACTION_TYPES = {
    "ReopenTicket": {
        "object_type": "Ticket",
        "operation": "update",
        "parameters": {
            "reason": {"type": "string", "required": True},
        },
        "submission_criteria": [
            {
                "description": "Ticket must currently be closed to reopen it",
                "check": "current_state", "field": "status", "operator": "equals", "value": "closed",
            },
        ],
        "mutations": [
            {"set": {"property": "status", "value": "open"}},
            {"set": {"property": "reopen_reason", "value": "parameter.reason"}},
        ],
    },
}

TEST_ROLES = {
    "support_lead": {"allowed_actions": [
        "execute:ReopenTicket",
        "read:Ticket", "read:Ticket.ticket_id", "read:Ticket.status", "read:Ticket.reopen_reason",
    ]},
}

TEST_USERS = {
    "lead": {"region": "us-west", "role": "support_lead"},
    "nobody": {"region": "us-west"},
    "wrong_region": {"region": "us-east", "role": "support_lead"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def write_mediator(tmp_path):
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE tickets (ticket_id TEXT PRIMARY KEY, region TEXT, status TEXT, reopen_reason TEXT);
        INSERT INTO tickets VALUES ('t1', 'us-west', 'closed', NULL);
        INSERT INTO tickets VALUES ('t2', 'us-west', 'open', NULL);
    """)
    conn.commit()
    conn.close()

    adapters = _build_adapters({"primary": {"adapter": "sqlite", "connection": {"path": db}}})
    mediator = DataMediator(TEST_SCHEMA, adapters, {"Ticket": "primary"}, TEST_ROLES)
    return WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES)


def test_valid_action_call_succeeds_end_to_end(write_mediator):
    lead = _record("lead")
    pending = write_mediator.propose_action(lead, "ReopenTicket", "t1", {"reason": "customer followup"})
    outcome = write_mediator.confirm_and_execute(pending, approved=True)

    assert outcome == {"status": "written", "object_id": "t1"}
    # Including the field that started genuinely NULL -- the real
    # adapter-level fix, proven here through the FULL WriteMediator path.
    assert write_mediator.mediator.get_field(lead, "Ticket", "t1", "status") == "open"
    assert write_mediator.mediator.get_field(lead, "Ticket", "t1", "reopen_reason") == "customer followup"


def test_mutations_resolve_both_literal_and_parameter_references(write_mediator):
    lead = _record("lead")
    pending = write_mediator.propose_action(lead, "ReopenTicket", "t1", {"reason": "a specific reason"})
    # "status" is a LITERAL in the action's own mutations ("open");
    # "reopen_reason" is a "parameter.reason" reference -- both must
    # resolve correctly into the SAME changes dict.
    assert pending.changes == {"status": "open", "reopen_reason": "a specific reason"}


def test_submission_criteria_blocks_an_invalid_state_transition(write_mediator):
    # t2 is already open -- the current_state criterion must block this.
    with pytest.raises(SubmissionCriteriaViolation, match="must currently be closed"):
        write_mediator.propose_action(_record("lead"), "ReopenTicket", "t2", {"reason": "x"})


def test_missing_required_parameter_is_rejected(write_mediator):
    with pytest.raises(ValueError, match="Missing required parameter"):
        write_mediator.propose_action(_record("lead"), "ReopenTicket", "t1", {})


def test_undeclared_parameter_is_rejected(write_mediator):
    # "Explicit and safe" -- an extra, undeclared parameter is REJECTED
    # outright, never silently ignored.
    with pytest.raises(ValueError, match="Unknown parameter"):
        write_mediator.propose_action(_record("lead"), "ReopenTicket", "t1", {"reason": "x", "hacked": "y"})


def test_rbac_denial_without_an_execute_grant(write_mediator):
    with pytest.raises(PermissionError, match="execute:ReopenTicket"):
        write_mediator.propose_action(_record("nobody"), "ReopenTicket", "t1", {"reason": "x"})


def test_mac_denial_even_with_execute_granted(write_mediator):
    # Action-level RBAC does NOT bypass MAC -- proves the two gates
    # are still genuinely independent under the new authorization model.
    with pytest.raises(PermissionError, match="cannot modify"):
        write_mediator.propose_action(_record("wrong_region"), "ReopenTicket", "t1", {"reason": "x"})


def test_unknown_action_type_name_raises(write_mediator):
    with pytest.raises(ValueError, match="Unknown action_type"):
        write_mediator.propose_action(_record("lead"), "TotallyFakeAction", "t1", {})


def test_denied_action_does_not_double_log(write_mediator, isolated_audit_log):
    # Regression test for a real bug caught while building this: MAC
    # denial used to log_access() TWICE for the same outcome (once
    # right after RBAC with mac_allowed=None, once again after MAC was
    # evaluated). Exactly ONE access_check entry must exist per call.
    from tests.conftest import read_audit_log

    with pytest.raises(PermissionError):
        write_mediator.propose_action(_record("wrong_region"), "ReopenTicket", "t1", {"reason": "x"})

    entries = read_audit_log(isolated_audit_log)
    execute_entries = [e for e in entries if e.get("action") == "execute:ReopenTicket"]
    assert len(execute_entries) == 1
    assert execute_entries[0]["mac_allowed"] is False
    assert execute_entries[0]["rbac_allowed"] is True
