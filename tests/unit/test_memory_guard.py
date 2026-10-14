"""
Agent memory (E-14), built 14 Oct to the owner's three answers:

  WHAT    a fact about one object, in a sentence
  WRITTEN only when a person asks
  STALE   when a field it was written from has changed since

core/memory/store.py keeps the rows; core/memory/guard.py decides who
sees, writes and forgets one -- live, on every call. These tests use the
real mediator over the shared Author/Book fixture: auth_001 is org-a,
auth_002 org-b.

THE TWO GUARANTEES WORTH BREAKING, and the controls that do
(scripts/check_controls.py, "E-14"):
  - a memory is hidden from a reader who cannot see every field it was
    written from (the sentence may repeat one of them);
  - a stale memory is never given to the agent.
"""

import sqlite3

import pytest

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import resolve_user_record
from core.memory.guard import MemoryGuard
from core.memory.store import MAX_TEXT, MemoryStore
from core.ontology.mediator import DataMediator
from tests.conftest import author_book_mediator, scripted_llm_client

FULL = ["read:Author", "read:Author.author_id", "read:Author.org_id", "read:Author.name"]
TEST_ROLES = {
    "reader": {"allowed_actions": FULL},
    # Everything but the name.
    "narrow": {"allowed_actions": ["read:Author", "read:Author.author_id", "read:Author.org_id"]},
    "editor": {"allowed_actions": [*FULL, "write:Author"]},
}
TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "carol": {"org_id": "org-a", "role": "reader"},
    "nina": {"org_id": "org-a", "role": "narrow"},
    "ed": {"org_id": "org-a", "role": "editor"},
    "bob": {"org_id": "org-b", "role": "reader"},
}


def _user(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def mediator(test_db_path, test_schema) -> DataMediator:
    return author_book_mediator(test_db_path, test_schema, TEST_ROLES)


@pytest.fixture
def guard(mediator, tmp_path) -> MemoryGuard:
    return MemoryGuard(MemoryStore(tmp_path / "memories.db"), mediator, TEST_ROLES)


def _rename(test_db_path, author_id, name):
    with sqlite3.connect(test_db_path) as conn:
        conn.execute("UPDATE authors SET name = ? WHERE author_id = ?", (name, author_id))


class TestWriting:
    def test_a_person_remembers_a_fact_and_sees_it(self, guard):
        memory = guard.remember(_user("alice"), "Author", "auth_001", "  prefers   email ")

        assert memory.text == "prefers email"
        assert memory.author == "alice"
        assert [(m.text, stale) for m, stale in guard.visible(_user("alice"), "Author", "auth_001")] \
            == [("prefers email", False)]

    def test_sources_are_fingerprints_of_what_the_writer_could_read(self, guard):
        memory = guard.remember(_user("nina"), "Author", "auth_001", "x")

        assert set(memory.sources) == {"org_id"}
        assert "org-a" not in str(memory.sources)

    def test_an_object_in_another_org_cannot_be_written_about(self, guard):
        assert guard.remember(_user("bob"), "Author", "auth_001", "x") is None

    def test_an_object_that_does_not_exist_cannot_be_written_about(self, guard):
        assert guard.remember(_user("alice"), "Author", "no_such_author", "x") is None
        assert guard.remember(_user("alice"), "NoSuchType", "auth_001", "x") is None

    @pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_TEXT + 1)])
    def test_empty_or_overlong_text_is_refused(self, guard, text):
        with pytest.raises(ValueError):
            guard.remember(_user("alice"), "Author", "auth_001", text)


class TestWhoSees:
    def test_another_org_sees_nothing(self, guard):
        guard.remember(_user("alice"), "Author", "auth_001", "x")

        assert guard.visible(_user("bob"), "Author", "auth_001") == []

    def test_a_reader_missing_a_source_field_does_not_see_it(self, guard):
        guard.remember(_user("alice"), "Author", "auth_001", "Ada signs as A.L.")

        assert guard.visible(_user("nina"), "Author", "auth_001") == []

    def test_a_memory_from_fewer_fields_is_seen_by_a_wider_reader(self, guard):
        """THE CONTROL for the one above: the rule is a subset test, not
        'the same role as the author'."""
        guard.remember(_user("nina"), "Author", "auth_001", "org-a account")

        assert len(guard.visible(_user("alice"), "Author", "auth_001")) == 1

    def test_a_grant_withdrawn_hides_it_at_once(self, guard):
        guard.remember(_user("alice"), "Author", "auth_001", "x")
        TEST_USERS["alice"]["role"] = "narrow"
        try:
            assert guard.visible(_user("alice"), "Author", "auth_001") == []
        finally:
            TEST_USERS["alice"]["role"] = "reader"


class TestStaleness:
    def test_a_changed_source_marks_it_stale_and_keeps_it_from_the_agent(self, guard, test_db_path):
        guard.remember(_user("alice"), "Author", "auth_001", "goes by Ada")
        _rename(test_db_path, "auth_001", "Augusta King")

        [(memory, stale)] = guard.visible(_user("alice"), "Author", "auth_001")
        assert stale
        assert guard.fresh(_user("alice"), "Author", "auth_001") == []

    def test_an_unchanged_object_stays_fresh(self, guard):
        """THE CONTROL: staleness is about change, not about age."""
        guard.remember(_user("alice"), "Author", "auth_001", "goes by Ada")

        assert [m.text for m in guard.fresh(_user("alice"), "Author", "auth_001")] == ["goes by Ada"]

    def test_a_field_the_memory_was_not_written_from_does_not_stale_it(self, guard, test_db_path):
        guard.remember(_user("nina"), "Author", "auth_001", "x")
        _rename(test_db_path, "auth_001", "Augusta King")

        assert [stale for _, stale in guard.visible(_user("alice"), "Author", "auth_001")] == [False]


class TestForgetting:
    def test_the_author_may_forget_it(self, guard):
        memory = guard.remember(_user("alice"), "Author", "auth_001", "x")

        assert guard.forget(_user("alice"), memory.memory_id)
        assert guard.visible(_user("alice"), "Author", "auth_001") == []

    def test_another_reader_may_not(self, guard):
        memory = guard.remember(_user("alice"), "Author", "auth_001", "x")

        assert not guard.forget(_user("carol"), memory.memory_id)
        assert len(guard.visible(_user("alice"), "Author", "auth_001")) == 1

    def test_someone_who_may_change_the_object_may(self, guard):
        memory = guard.remember(_user("alice"), "Author", "auth_001", "x")

        assert guard.forget(_user("ed"), memory.memory_id)

    def test_nobody_forgets_what_they_cannot_see(self, guard):
        memory = guard.remember(_user("alice"), "Author", "auth_001", "x")
        TEST_USERS["bob"]["role"] = "editor"
        try:
            assert not guard.forget(_user("bob"), memory.memory_id)
        finally:
            TEST_USERS["bob"]["role"] = "reader"

    def test_an_unknown_id_is_simply_false(self, guard):
        assert not guard.forget(_user("alice"), "no-such-memory")


class TestErasure:
    def test_forget_erased_matches_by_salted_hash(self, guard, tmp_path):
        from core.mirror.erasure import ErasureRegister

        guard.remember(_user("alice"), "Author", "auth_001", "x")
        guard.remember(_user("bob"), "Author", "auth_002", "z")
        register = ErasureRegister(tmp_path / "erasures.db")
        register.record([("Author", "auth_001")], "test", "test")

        assert guard.store.forget_erased(register.hasher(), register.hashes_by_type()) == 1
        assert guard.store.about("Author", "auth_001") == []
        assert len(guard.store.about("Author", "auth_002")) == 1


class TestTheAgentReadsThem:
    def _run(self, guard, mediator, steps):
        loop = AgentLoop(scripted_llm_client([*steps, {"step": "finish"}]), mediator, memory=guard)
        return loop.run(_user("alice"), "test query").gathered

    def test_reading_an_object_brings_its_fresh_memories_once(self, guard, mediator):
        guard.remember(_user("alice"), "Author", "auth_001", "prefers email")
        read = {"step": "get_object", "object_type": "Author", "object_id": "auth_001",
                "field_names": ["name"]}

        gathered = self._run(guard, mediator, [read, {**read, "field_names": ["org_id"]}])

        memories = [entry for entry in gathered if entry["step"] == "memory"]
        assert [entry["result"] for entry in memories] == [["prefers email"]]
        assert memories[0]["note"] == AgentLoop.MEMORY_LABEL

    def test_a_stale_memory_is_not_given_to_the_agent(self, guard, mediator, test_db_path):
        guard.remember(_user("alice"), "Author", "auth_001", "goes by Ada")
        _rename(test_db_path, "auth_001", "Augusta King")

        gathered = self._run(guard, mediator, [
            {"step": "get_object", "object_type": "Author", "object_id": "auth_001",
             "field_names": ["name"]}])

        assert not any(entry["step"] == "memory" for entry in gathered)

    def test_a_memory_is_not_a_plan_steps_value(self):
        gathered = [{"step": "get_field", "result": "Ada"},
                    {"step": "memory", "result": ["prefers email"]}]

        assert AgentLoop._produced(gathered, 0) == "Ada"
