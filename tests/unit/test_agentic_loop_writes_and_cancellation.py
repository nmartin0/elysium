"""
Tests for the two behaviors added when AgentLoop stopped confirming
writes itself: a proposed write STOPS run() immediately (never a
second proposal in the same run, never auto-executed), and cancel_event
skips further hops. Real DataMediator/WriteMediator, real SQLite --
only the LLM client is mocked.
"""

import json
import threading
from unittest.mock import MagicMock

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_mediator import WriteMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "editor"},
}

TEST_ROLES = {
    "editor": {"allowed_actions": ["read:Author", "read:Author.name", "write:Author.name"]},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def mediator_and_write_mediator(test_db_path, test_schema):
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["silo"] for object_type, type_def in test_schema.items()}
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES)
    write_mediator = WriteMediator(mediator, TEST_ROLES)
    return mediator, write_mediator


def _loop_with_mocked_llm(mediator, write_mediator, scripted_steps):
    client = MagicMock()
    call_count = {"n": 0}

    def fake_chat(*args, **kwargs):
        idx = min(call_count["n"], len(scripted_steps) - 1)
        call_count["n"] += 1
        return json.dumps(scripted_steps[idx])

    client.chat.side_effect = fake_chat
    return AgentLoop(client, mediator, write_mediator=write_mediator)


def test_propose_write_stops_the_loop_immediately(mediator_and_write_mediator):
    mediator, write_mediator = mediator_and_write_mediator
    # A "finish" step scripted AFTER the propose_write must never be
    # reached -- the loop should stop at the proposal itself, not
    # continue on to it.
    loop = _loop_with_mocked_llm(mediator, write_mediator, [
        {"step": "propose_write", "object_type": "Author", "object_id": "auth_001",
         "action": "update", "changes": {"name": "New Name"}},
        {"step": "finish"},
    ])
    result = loop.run(_record("alice"), "test query")

    assert result.pending_write is not None
    assert result.pending_write.object_type == "Author"
    assert result.pending_write.changes == {"name": "New Name"}


def test_propose_write_does_not_touch_the_database(mediator_and_write_mediator):
    # AgentLoop must NEVER call confirm_and_execute() itself -- proposing
    # is as far as it goes; the database must be completely untouched.
    mediator, write_mediator = mediator_and_write_mediator
    loop = _loop_with_mocked_llm(mediator, write_mediator, [
        {"step": "propose_write", "object_type": "Author", "object_id": "auth_001",
         "action": "update", "changes": {"name": "Should Not Apply"}},
    ])
    loop.run(_record("alice"), "test query")

    real_value = mediator.get_field(_record("alice"), "Author", "auth_001", "name")
    assert real_value == "Ada Lovelace"  # unchanged from conftest.py's seed data


def test_cancel_event_set_before_first_hop_stops_immediately(mediator_and_write_mediator):
    mediator, write_mediator = mediator_and_write_mediator
    loop = _loop_with_mocked_llm(mediator, write_mediator, [
        {"step": "get_field", "object_type": "Author", "object_id": "auth_001", "field_name": "name"},
    ])
    cancel_event = threading.Event()
    cancel_event.set()  # already cancelled before run() is even called

    result = loop.run(_record("alice"), "test query", cancel_event=cancel_event)

    assert result.cancelled is True
    assert result.gathered == []  # no hop ever executed


def test_no_cancel_event_behaves_exactly_as_before(mediator_and_write_mediator):
    # cancel_event is optional -- omitting it entirely must not change
    # behavior at all.
    mediator, write_mediator = mediator_and_write_mediator
    loop = _loop_with_mocked_llm(mediator, write_mediator, [
        {"step": "get_field", "object_type": "Author", "object_id": "auth_001", "field_name": "name"},
        {"step": "finish"},
    ])
    result = loop.run(_record("alice"), "test query")

    assert result.cancelled is False
    assert result.pending_write is None
    assert result.gathered[0]["result"] == "Ada Lovelace"
