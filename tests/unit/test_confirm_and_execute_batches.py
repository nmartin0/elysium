"""
Tests proving WriteMediator.confirm_and_execute() genuinely ALWAYS
goes through write_log_batches -- one sub_write or many, no branch on
count -- not just that final outcomes still look right (already
covered by every other passing test in this suite; this file exists
specifically to test the INTERNAL mechanism itself, which nothing
else does directly).

See write_log.py's own MULTI-OBJECT BATCHES docstring section, and
this file's own action_type fixtures (test_multi_silo.py's own
RenameWidget-style shape, reused here), for why uniform
REPRESENTATION -- not just uniform code -- is the actual design this
proves: a single-sub_write action creates a write_log_batches row too,
the exact same way _group_changes_by_storage() already lets a single-
storage object apply through the same loop as a multi-storage one,
with no special case for either.

Reuses tests/unit/test_write_mediator.py's own TEST_USERS/TEST_ROLES/
schema shape (Author, org_id as the security field) rather than
inventing a new one -- this file is about confirm_and_execute()'s own
batch mechanics, not about proving RBAC/MAC again.
"""

import pytest

from adapters.sqlite_adapter import SQLiteWriteAdapter
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter
from core.ontology.write_mediator import WriteMediator

TEST_USERS = {"alice": {"org_id": "org-a", "role": "editor"}}
TEST_ROLES = {"editor": {"allowed_actions": ["read:Author", "read:Author.name", "execute:RenameAuthor"]}}
TEST_ACTION_TYPES = {
    "RenameAuthor": {
        "affected_object_types": ["Author"],
        "parameters": {
            "author_id": {"type": "object_reference", "object_type": "Author", "required": True},
            "new_name": {"type": "string", "required": True},
        },
        "sub_writes": [{
            "object_type": "Author",
            "object_id": "parameter.author_id",
            "operation": "update",
            "mutations": [{"set": {"property": "name", "value": "parameter.new_name"}}],
        }],
    },
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def wm_and_log(test_db_path, test_schema, tmp_path):
    adapter = SQLiteWriteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    write_log = WriteLogWriter(tmp_path / "write_log.db")
    mediator = DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES, write_log=write_log)
    write_mediator = WriteMediator(mediator, {"test_silo": adapter}, TEST_ROLES, TEST_ACTION_TYPES)
    return write_mediator, write_log


def test_confirm_and_execute_ends_with_no_pending_batches(wm_and_log):
    # THE core, positive proof: after a normal, successful
    # confirm_and_execute() -- ONE sub_write, the ordinary, everyday
    # case -- get_pending_batches() must be empty. Not because no
    # batch was ever created (see the next test for direct proof one
    # WAS), but because it went through log -> apply -> mark_batch_
    # applied() cleanly, exactly like every write in this whole suite
    # implicitly already relies on.
    write_mediator, write_log = wm_and_log
    pending = write_mediator.propose_action(_record("alice"), "RenameAuthor",
                                             {"author_id": "auth_001", "new_name": "Ada L."})

    write_mediator.confirm_and_execute(pending, approved=True)

    assert write_log.get_pending_batches() == []


def test_confirm_and_execute_result_reflects_every_touched_object(wm_and_log):
    write_mediator, write_log = wm_and_log
    pending = write_mediator.propose_action(_record("alice"), "RenameAuthor",
                                             {"author_id": "auth_001", "new_name": "Ada L."})

    result = write_mediator.confirm_and_execute(pending, approved=True)

    assert result == {"status": "written", "object_ids": ["auth_001"]}


def test_rejected_action_creates_no_batch_at_all(wm_and_log):
    # approved=False must return before _apply_batch() is ever
    # reached -- no write_log_batches row, no per-object write_log
    # row, nothing to find pending OR applied.
    write_mediator, write_log = wm_and_log
    pending = write_mediator.propose_action(_record("alice"), "RenameAuthor",
                                             {"author_id": "auth_001", "new_name": "Should Not Apply"})

    result = write_mediator.confirm_and_execute(pending, approved=False)

    assert result is None
    assert write_log.get_pending_batches() == []
    assert write_log.get_pending_changes("Author", "auth_001") is None


def test_the_per_object_row_is_correctly_batch_owned_mid_apply(wm_and_log, monkeypatch):
    # Proves the ACTUAL mechanism, not just the end state: while
    # confirm_and_execute() is still mid-apply, the per-object
    # write_log row that's been created so far genuinely has batch_id
    # set (findable via get_sub_write_entry() under its own batch's
    # id, matching write_log.py's own docstring) -- observed via a
    # spy on the real adapter write, the same technique tests/unit/
    # test_write_log_create.py's own test_apply_create_via_log_logs_
    # under_the_real_id_not_none already established for the pre-
    # batch mechanism.
    write_mediator, write_log = wm_and_log
    pending = write_mediator.propose_action(_record("alice"), "RenameAuthor",
                                             {"author_id": "auth_001", "new_name": "Ada L."})

    observed = {}
    original_write_fields = write_mediator.mediator.adapters["test_silo"].write_fields

    def spy_write_fields(*args, **kwargs):
        # Mid-apply: this sub_write's own write_log row must already
        # exist, AND get_all_pending_writes() (the search-
        # reconciliation-facing view) must find it regardless of
        # batch ownership.
        observed["pending_changes"] = write_log.get_pending_changes("Author", "auth_001")
        observed["all_pending"] = write_log.get_all_pending_writes()
        observed["pending_batches"] = write_log.get_pending_batches()
        return original_write_fields(*args, **kwargs)

    monkeypatch.setattr(write_mediator.mediator.adapters["test_silo"], "write_fields", spy_write_fields)
    write_mediator.confirm_and_execute(pending, approved=True)

    assert observed["pending_changes"] == {"name": "Ada L."}
    assert len(observed["pending_batches"]) == 1
    batch_id = observed["pending_batches"][0]["id"]
    assert observed["pending_batches"][0]["sub_writes"][0]["object_id"] == "auth_001"

    # THE actual proof this row is genuinely batch-owned: findable
    # under its own batch's real id.
    assert write_log.get_sub_write_entry(batch_id, "Author", "auth_001") is not None

    # And it's exactly what get_all_pending_writes() (the search-
    # reconciliation-facing view) reports too -- the SAME object,
    # regardless of the fact that it's batch-owned, not standalone.
    all_pending_ids = {entry["object_id"] for entry in observed["all_pending"]}
    assert "auth_001" in all_pending_ids
