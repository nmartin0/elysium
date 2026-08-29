"""
Tests for AgentLoop's named-action-types integration (action-types-
redesign branch): the new "propose_action" step in _execute_step(),
and the distinct rejected_business_rule category, kept genuinely
independent from rejected_invalid_step's own counter and cap.

Tests _execute_step() DIRECTLY, not through run()/next_step() -- as of
this branch, core/llm/agent_step_prompt.py does not yet describe
"propose_action" as a valid step to the model at all (that's separate,
still-pending work), so next_step() correctly rejects it as an
unrecognized step before ever reaching _execute_step() (confirmed
directly while building this, not assumed). Testing _execute_step()
directly isolates the EXECUTION mechanism this file is actually about
from that separate, not-yet-built validation layer.

t1 starts "open" -- ReopenTicket's own submission criterion requires
"closed", so every propose_action call in this file is a DELIBERATE
business-rule violation, proving the rejection path specifically.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

from core.deployment_loader import _build_adapters
from core.intermediate_layer.auth import resolve_user_record
from core.agent.agentic_loop import AgentLoop
from core.ontology.mediator import DataMediator
from core.ontology.write_mediator import WriteMediator

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
        "parameters": {"reason": {"type": "string", "required": True}},
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
    "lead": {"allowed_actions": ["execute:ReopenTicket", "read:Ticket", "read:Ticket.ticket_id"]},
}

TEST_USERS = {
    "lead": {"region": "us-west", "role": "lead"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def loop(tmp_path):
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE tickets (ticket_id TEXT PRIMARY KEY, region TEXT, status TEXT, reopen_reason TEXT);
        INSERT INTO tickets VALUES ('t1', 'us-west', 'open', NULL);
    """)
    conn.commit()
    conn.close()

    adapters = _build_adapters({"primary": {"adapter": "sqlite", "connection": {"path": db}}})
    write_log_db_path = tmp_path / "write_log.db"
    mediator = DataMediator(TEST_SCHEMA, adapters, {"Ticket": "primary"}, TEST_ROLES,
                             write_log_db_path=write_log_db_path)
    write_mediator = WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES, write_log_db_path=write_log_db_path)
    return AgentLoop(MagicMock(), mediator, write_mediator=write_mediator,
                      max_hops=5, max_consecutive_invalid_steps=2)


def _reopen_step():
    return {"step": "propose_action", "action_type": "ReopenTicket", "object_id": "t1", "parameters": {"reason": "x"}}


def test_business_rule_violation_produces_rejected_business_rule_not_invalid_step(loop):
    lead = _record("lead")
    visible_schema = loop.mediator.visible_schema(lead)
    gathered = []

    consecutive_invalid, consecutive_business_rule, should_stop, pending = loop._execute_step(
        _reopen_step(), lead, visible_schema, gathered, 0, 0
    )

    assert gathered[-1]["step"] == "rejected_business_rule"
    assert "must currently be closed" in gathered[-1]["note"]
    assert (consecutive_invalid, consecutive_business_rule, should_stop, pending) == (0, 1, False, None)


def test_invalid_step_does_not_affect_the_business_rule_counter(loop):
    # A genuinely different kind of failure -- search_object with an
    # unfilterable field name, which DOES raise ValueError (unlike
    # get_field() on an unknown field, which returns None gracefully
    # per this project's uniform-denial design, not an exception).
    lead = _record("lead")
    visible_schema = loop.mediator.visible_schema(lead)
    gathered = []

    invalid_step = {"step": "search_object", "object_type": "Ticket", "filter": {"totally_fake_field": "x"}}
    consecutive_invalid, consecutive_business_rule, should_stop, pending = loop._execute_step(
        invalid_step, lead, visible_schema, gathered, 0, 1  # business_rule already at 1
    )

    assert gathered[-1]["step"] == "rejected_invalid_step"
    assert consecutive_invalid == 1
    # THE actual property under test: an invalid step must NOT reset,
    # increment, or otherwise touch the OTHER counter.
    assert consecutive_business_rule == 1


def test_business_rule_rejections_stop_at_their_own_cap(loop):
    lead = _record("lead")
    visible_schema = loop.mediator.visible_schema(lead)
    gathered = []

    _, count, should_stop, _ = loop._execute_step(_reopen_step(), lead, visible_schema, gathered, 0, 0)
    assert should_stop is False
    _, count, should_stop, _ = loop._execute_step(_reopen_step(), lead, visible_schema, gathered, 0, count)
    assert count == 2
    assert should_stop is True


def test_a_genuine_success_resets_both_counters(loop):
    lead = _record("lead")
    visible_schema = loop.mediator.visible_schema(lead)
    gathered = []

    success_step = {"step": "search_object", "object_type": "Ticket", "filter": {"ticket_id": "t1"}}
    consecutive_invalid, consecutive_business_rule, should_stop, pending = loop._execute_step(
        success_step, lead, visible_schema, gathered, 5, 5
    )
    assert (consecutive_invalid, consecutive_business_rule) == (0, 0)


def test_propose_action_step_is_rejected_gracefully_when_writes_are_disabled():
    # write_mediator=None -- writes fully disabled for this deployment.
    # The "Writes are not enabled" ValueError is raised INSIDE
    # _execute_step()'s own try block, so it's caught by the SAME
    # except (ValueError, TypeError, PermissionError) clause as any
    # other invalid step -- treated as a recoverable mistake, not an
    # uncaught crash. Matches propose_write()'s identical behavior
    # exactly (confirmed directly, not assumed, after an earlier
    # version of this test incorrectly expected an uncaught raise).
    adapters = _build_adapters({})
    mediator = DataMediator({}, adapters, {}, TEST_ROLES)
    loop_no_writes = AgentLoop(MagicMock(), mediator, write_mediator=None)
    lead = _record("lead")
    gathered = []

    consecutive_invalid, consecutive_business_rule, should_stop, pending = loop_no_writes._execute_step(
        _reopen_step(), lead, {}, gathered, 0, 0
    )

    assert gathered[-1]["step"] == "rejected_invalid_step"
    assert "Writes are not enabled" in gathered[-1]["note"]
    assert (consecutive_invalid, consecutive_business_rule, should_stop, pending) == (1, 0, False, None)


def test_rejected_business_rule_is_bookkeeping_stripped_before_synthesis():
    # Same treatment as rejected_invalid_step/rejected_duplicate --
    # process bookkeeping, never real gathered data handed to synthesis.
    gathered = [
        {"step": "rejected_business_rule", "note": "x"},
        {"step": "search_object", "object_type": "Ticket", "filter": {}, "result": ["t1"]},
    ]
    real_data = AgentLoop.filter_real_data(gathered)
    assert len(real_data) == 1
    assert real_data[0]["step"] == "search_object"
