"""
Tests for core/agent/agentic_loop.py's own get_object handling -- THE
real, end-to-end proof that a single get_object step, scripted from a
real (if mocked) model response, expands into multiple get_field-
shaped gathered[] entries, not one get_object-shaped entry. See
core/ontology/mediator.py's DataMediator.get_object() (the thin, per-
field wrapper this ultimately calls) and tests/unit/test_agent_step_
prompt.py (next_step()'s own parsing/validation of the step itself,
in isolation) for the two halves this file's own tests build on top
of, rather than re-prove.

Real DataMediator, real SQLite (test_schema/test_db_path from tests/
conftest.py, the Author/Book fixture) -- only the LLM client is
scripted, matching test_agentic_loop_writes_and_cancellation.py's own
established pattern.

alice: org-a, full read grants on Author (name, books) and Book
(title, author_id) -- reused directly from tests/unit/test_mediator.py's
own TEST_ROLES shape, not reinvented.
"""

from adapters.sqlite_adapter import SQLiteWriteAdapter
from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from tests.conftest import scripted_llm_client

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
}
TEST_ROLES = {
    "reader": {"allowed_actions": [
        "read:Author", "read:Author.author_id", "read:Author.name", "read:Author.books",
        "read:Book", "read:Book.book_id", "read:Book.title", "read:Book.author_id",
    ]},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


def _mediator(test_db_path, test_schema) -> DataMediator:
    adapter = SQLiteWriteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    return DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES)


def test_get_object_expands_into_one_gathered_entry_per_field(test_db_path, test_schema):
    mediator = _mediator(test_db_path, test_schema)
    loop = AgentLoop(scripted_llm_client([
        {"step": "get_object", "object_type": "Author", "object_id": "auth_001", "field_names": ["name", "books"]},
        {"step": "finish"},
    ]), mediator)

    result = loop.run(_record("alice"), "test query")

    # TWO separate get_field-SHAPED entries, not one get_object entry.
    get_field_entries = [item for item in result.gathered if item["step"] == "get_field"]
    assert len(get_field_entries) == 2
    assert {item["field_name"] for item in get_field_entries} == {"name", "books"}
    assert not any(item["step"] == "get_object" for item in result.gathered)

    by_field = {item["field_name"]: item["result"] for item in get_field_entries}
    assert by_field["name"] == "Ada Lovelace"
    assert set(by_field["books"]) == {1, 2}

    # Every expanded entry carries the SAME object_type/object_id the
    # original get_object step named -- proving the expansion didn't
    # lose or garble that shared context per field.
    for item in get_field_entries:
        assert item["object_type"] == "Author"
        assert item["object_id"] == "auth_001"


def test_get_object_result_is_indistinguishable_from_separate_get_field_calls(test_db_path, test_schema):
    # THE real point of the expansion design: everything downstream of
    # `gathered` (duplicate detection, the model's own "already
    # gathered" prompt text) must treat a get_object result EXACTLY
    # like it would treat the same fields fetched one at a time.
    # Proven here by requesting "name" via get_object, then trying to
    # request the SAME field again via an ordinary get_field -- the
    # loop's own duplicate-request handling must recognize this as a
    # genuine repeat and reject it, exactly as it would for two
    # consecutive get_field calls on the same field.
    mediator = _mediator(test_db_path, test_schema)
    loop = AgentLoop(scripted_llm_client([
        {"step": "get_object", "object_type": "Author", "object_id": "auth_001", "field_names": ["name"]},
        {"step": "get_field", "object_type": "Author", "object_id": "auth_001", "field_name": "name"},
        {"step": "finish"},
    ]), mediator, max_consecutive_duplicates=1)

    result = loop.run(_record("alice"), "test query")

    get_field_entries = [item for item in result.gathered if item["step"] == "get_field"]
    assert len(get_field_entries) == 1, (
        "the repeated get_field on a field already gathered via get_object "
        "should have been rejected as a duplicate, not fetched again"
    )


def test_get_object_partial_denial_still_expands_every_field(test_db_path, test_schema):
    # bob (different org) is MAC-denied on EVERY field of auth_001 --
    # proves get_object's own per-field Nones still each get their own
    # get_field-shaped entry, not silently dropped or collapsed.
    mediator = _mediator(test_db_path, test_schema)
    bob_users = {**TEST_USERS, "bob": {"org_id": "org-b", "role": "reader"}}
    loop = AgentLoop(scripted_llm_client([
        {"step": "get_object", "object_type": "Author", "object_id": "auth_001", "field_names": ["name", "books"]},
        {"step": "finish"},
    ]), mediator)

    bob_record = resolve_user_record(bob_users, "bob", "org_id")
    result = loop.run(bob_record, "test query")

    get_field_entries = [item for item in result.gathered if item["step"] == "get_field"]
    assert len(get_field_entries) == 2
    assert all(item["result"] is None for item in get_field_entries)
