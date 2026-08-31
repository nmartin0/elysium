"""
Tests for core/ontology/write_log.py's multi-object batch capability
-- write_log_batches, get_pending_batches(), get_pending_changes()'s
read-path fallback, get_sub_write_entry() (per-sub-write status
lookup), and get_all_pending_writes() (the flat, reconciliation-scale
view that replaced the older get_pending_entries(), retired once its
own batch_id IS NULL filter's only reason for existing -- avoiding
double-processing against the pre-rebuild resume_pending_writes() --
no longer applied). See write_log.py's own MULTI-OBJECT BATCHES
docstring section for the full mechanism this proves.

Deliberately tests the WriteLog class directly, in isolation --
mirrors the same discipline core/ontology/action_types.py's own
schema-load validation was built and proven with, before
propose_action() was ever rebuilt to use it.
NOTE: as of this file's own writing, WriteMediator.confirm_and_
execute() and resume_pending_writes() HAVE since been rebuilt to use
this class's full batch capability -- see tests/unit/test_confirm_
and_execute_batches.py and tests/unit/test_write_log_resume.py for
that integration-level proof; this file stays scoped to the WriteLog
class's own mechanics.
"""

from core.ontology.write_log import WriteLog


def _sub_write(object_type="Account", object_id="acc_1", operation="update",
                changes=None, expected_current_values=None):
    return {
        "object_type": object_type,
        "object_id": object_id,
        "operation": operation,
        "changes": changes if changes is not None else {"balance": 400},
        "expected_current_values": expected_current_values if expected_current_values is not None else {"balance": 500},
    }


def test_log_pending_batch_is_findable_via_get_pending_batches(tmp_path):
    write_log = WriteLog(tmp_path / "write_log.db")
    sub_writes = [_sub_write("Account", "acc_1"), _sub_write("Account", "acc_2")]

    batch_id = write_log.log_pending_batch(sub_writes, "alice", "TransferFunds(...)")

    batches = write_log.get_pending_batches()
    assert len(batches) == 1
    assert batches[0]["id"] == batch_id
    assert batches[0]["sub_writes"] == sub_writes
    assert batches[0]["user_id"] == "alice"
    assert batches[0]["description"] == "TransferFunds(...)"


def test_mark_batch_applied_removes_it_from_pending_batches(tmp_path):
    write_log = WriteLog(tmp_path / "write_log.db")
    batch_id = write_log.log_pending_batch([_sub_write()], "alice", "desc")

    write_log.mark_batch_applied(batch_id)

    assert write_log.get_pending_batches() == []


def test_get_pending_changes_falls_back_to_a_pending_batch(tmp_path):
    # THE core, positive proof: an object with NO per-object write_log
    # row yet (its own sub-write hasn't started applying) is still
    # found via the batch's own, already-declared intent.
    write_log = WriteLog(tmp_path / "write_log.db")
    write_log.log_pending_batch(
        [_sub_write("Account", "acc_1", changes={"balance": 400})], "alice", "desc"
    )

    assert write_log.get_pending_changes("Account", "acc_1") == {"balance": 400}


def test_get_pending_changes_batch_fallback_finds_the_right_sub_write_among_several(tmp_path):
    write_log = WriteLog(tmp_path / "write_log.db")
    write_log.log_pending_batch(
        [
            _sub_write("Account", "acc_1", changes={"balance": 400}),
            _sub_write("Account", "acc_2", changes={"balance": 600}),
        ],
        "alice", "desc",
    )

    assert write_log.get_pending_changes("Account", "acc_1") == {"balance": 400}
    assert write_log.get_pending_changes("Account", "acc_2") == {"balance": 600}


def test_get_pending_changes_batch_fallback_respects_object_type_too(tmp_path):
    # The SAME id string, genuinely different types -- must not
    # cross-match.
    write_log = WriteLog(tmp_path / "write_log.db")
    write_log.log_pending_batch(
        [_sub_write("Account", "shared_id", changes={"balance": 400})], "alice", "desc"
    )

    assert write_log.get_pending_changes("Order", "shared_id") is None


def test_get_pending_changes_returns_none_once_the_batch_is_applied(tmp_path):
    # Once a batch is marked applied, its own stale, no-longer-pending
    # intent must NOT keep surfacing for an object that never got its
    # own per-object write_log row at all (e.g. a batch with only one
    # sub-write, applied so quickly no reader ever raced it).
    write_log = WriteLog(tmp_path / "write_log.db")
    batch_id = write_log.log_pending_batch(
        [_sub_write("Account", "acc_1", changes={"balance": 400})], "alice", "desc"
    )
    write_log.mark_batch_applied(batch_id)

    assert write_log.get_pending_changes("Account", "acc_1") is None


def test_get_pending_changes_prefers_the_per_object_row_over_the_batch(tmp_path):
    # Once a sub-write's OWN write_log row exists (it has started
    # applying), that row -- not the batch's own, now-superseded
    # declaration -- is what get_pending_changes() must return. Uses a
    # DIFFERENT changes value on each to prove which one actually won.
    write_log = WriteLog(tmp_path / "write_log.db")
    batch_id = write_log.log_pending_batch(
        [_sub_write("Account", "acc_1", changes={"balance": 400})], "alice", "desc"
    )
    write_log.log_pending_update(
        "Account", "acc_1", {"balance": 999}, {"balance": 500}, "alice", "desc", batch_id=batch_id
    )

    assert write_log.get_pending_changes("Account", "acc_1") == {"balance": 999}


def test_get_pending_changes_returns_none_for_an_object_no_batch_mentions(tmp_path):
    write_log = WriteLog(tmp_path / "write_log.db")
    write_log.log_pending_batch(
        [_sub_write("Account", "acc_1", changes={"balance": 400})], "alice", "desc"
    )

    assert write_log.get_pending_changes("Account", "totally_unrelated_id") is None


def test_get_sub_write_entry_only_finds_it_under_the_correct_batch(tmp_path):
    # Replaces the old test_get_pending_entries_excludes_batch_owned_
    # rows, which tested get_pending_entries()'s own now-retired
    # batch_id IS NULL filter -- see write_log.py's own docstring for
    # why that filter's whole reason for existing (avoiding double-
    # processing against the OLD, pre-rebuild resume_pending_writes())
    # no longer applies. get_sub_write_entry() is the real, correctly-
    # scoped replacement for "is this row batch-owned, and by which
    # batch specifically" -- proven here both ways: found under its
    # own real batch_id, NOT found under an unrelated one.
    write_log = WriteLog(tmp_path / "write_log.db")
    real_batch_id = write_log.log_pending_batch([_sub_write("Account", "acc_1")], "alice", "batch desc")
    write_log.log_pending_update(
        "Account", "acc_1", {"balance": 400}, {"balance": 500}, "alice", "batch desc", batch_id=real_batch_id
    )
    other_batch_id = write_log.log_pending_batch([_sub_write("Account", "acc_99")], "alice", "other desc")

    assert write_log.get_sub_write_entry(real_batch_id, "Account", "acc_1") is not None
    assert write_log.get_sub_write_entry(other_batch_id, "Account", "acc_1") is None


def test_get_all_pending_writes_finds_ordinary_standalone_writes(tmp_path):
    # Replaces the old test_get_pending_entries_still_finds_ordinary_
    # standalone_writes -- get_all_pending_writes() is the general,
    # reconciliation-facing query now (see write_log.py's own
    # docstring), and must still correctly find genuinely standalone
    # writes (batch_id left as the default None), not just batch-owned
    # ones, even though nothing in the real system produces standalone
    # writes anymore now that confirm_and_execute() always batches.
    write_log = WriteLog(tmp_path / "write_log.db")
    write_log.log_pending_update("Account", "acc_1", {"balance": 1}, {"balance": 2}, "alice", "desc")
    write_log.log_pending_create("Account", "acc_2", {"balance": 1}, "alice", "desc")

    entries = write_log.get_all_pending_writes()

    assert {e["object_id"] for e in entries} == {"acc_1", "acc_2"}


def test_log_pending_create_also_accepts_a_batch_id(tmp_path):
    write_log = WriteLog(tmp_path / "write_log.db")
    batch_id = write_log.log_pending_batch(
        [_sub_write("Account", "acc_1", operation="create", changes={"balance": 0})], "alice", "desc"
    )
    write_log.log_pending_create("Account", "acc_1", {"balance": 0}, "alice", "desc", batch_id=batch_id)

    # Findable via get_sub_write_entry() under its own batch, same as update.
    assert write_log.get_sub_write_entry(batch_id, "Account", "acc_1") is not None
    # But still resolvable via the per-object row directly.
    assert write_log.get_pending_changes("Account", "acc_1") == {"balance": 0}
