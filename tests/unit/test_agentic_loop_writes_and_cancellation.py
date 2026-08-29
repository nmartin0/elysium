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
    "editor": {"allowed_actions": ["read:Author", "read:Author.name", "execute:RenameAuthor"]},
}

TEST_ACTION_TYPES = {
    "RenameAuthor": {
        "object_type": "Author",
        "operation": "update",
        "parameters": {"new_name": {"type": "string", "required": True}},
        "mutations": [{"set": {"property": "name", "value": "parameter.new_name"}}],
    },
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def mediator_and_write_mediator(test_db_path, test_schema, tmp_path):
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    write_log_db_path = tmp_path / "write_log.db"
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES,
                             write_log_db_path=write_log_db_path)
    write_mediator = WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES, write_log_db_path=write_log_db_path)
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


def test_propose_action_stops_the_loop_immediately(mediator_and_write_mediator):
    mediator, write_mediator = mediator_and_write_mediator
    # A "finish" step scripted AFTER the propose_action must never be
    # reached -- the loop should stop at the proposal itself, not
    # continue on to it.
    loop = _loop_with_mocked_llm(mediator, write_mediator, [
        {"step": "propose_action", "action_type": "RenameAuthor", "object_id": "auth_001",
         "parameters": {"new_name": "New Name"}},
        {"step": "finish"},
    ])
    result = loop.run(_record("alice"), "test query")

    assert result.pending_write is not None
    assert result.pending_write.object_type == "Author"
    assert result.pending_write.changes == {"name": "New Name"}


def test_propose_action_does_not_touch_the_database(mediator_and_write_mediator):
    # AgentLoop must NEVER call confirm_and_execute() itself -- proposing
    # is as far as it goes; the database must be completely untouched.
    mediator, write_mediator = mediator_and_write_mediator
    loop = _loop_with_mocked_llm(mediator, write_mediator, [
        {"step": "propose_action", "action_type": "RenameAuthor", "object_id": "auth_001",
         "parameters": {"new_name": "Should Not Apply"}},
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


def test_hit_max_hops_set_true_when_loop_genuinely_exhausts(mediator_and_write_mediator):
    mediator, write_mediator = mediator_and_write_mediator

    # A DIFFERENT search_object filter every single call -- this is
    # deliberate, not incidental: an identical repeated step would
    # trigger duplicate detection instead, stopping the loop for a
    # DIFFERENT reason before max_hops is ever reached. Varying the
    # step each time is what forces a genuine exhaustion. Searches by
    # "name" -- TEST_ROLES' "editor" role grants read:Author.name but
    # NOT read:Author.author_id, so author_id isn't a valid search key
    # for this role at all (the id_field needs its own explicit grant,
    # same as any other field -- searching by it here would correctly
    # be rejected as invalid criteria, a different test entirely).
    call_count = {"n": 0}
    client = MagicMock()

    def fake_chat(*args, **kwargs):
        call_count["n"] += 1
        return json.dumps({"step": "search_object", "object_type": "Author",
                            "filter": {"name": f"Author Number {call_count['n']}"}})

    client.chat.side_effect = fake_chat
    loop = AgentLoop(client, mediator, write_mediator=write_mediator, max_hops=3)

    result = loop.run(_record("alice"), "test query")

    assert result.hit_max_hops is True
    assert len(result.gathered) == 3  # exactly max_hops real hops taken


def test_hit_max_hops_stays_false_on_a_normal_finish(mediator_and_write_mediator):
    mediator, write_mediator = mediator_and_write_mediator
    loop = _loop_with_mocked_llm(mediator, write_mediator, [{"step": "finish"}])

    result = loop.run(_record("alice"), "test query")

    assert result.hit_max_hops is False


def test_hit_max_hops_stays_false_when_stopped_by_duplicate_cap(mediator_and_write_mediator):
    # A DIFFERENT way the loop can stop early (max_consecutive_duplicates
    # exceeded) -- hit_max_hops must specifically mean "ran out of hops,"
    # not become a generic "stopped before finishing cleanly" flag.
    mediator, write_mediator = mediator_and_write_mediator
    loop = _loop_with_mocked_llm(mediator, write_mediator, [
        {"step": "get_field", "object_type": "Author", "object_id": "auth_001", "field_name": "name"},
    ])

    result = loop.run(_record("alice"), "test query")

    assert result.hit_max_hops is False
