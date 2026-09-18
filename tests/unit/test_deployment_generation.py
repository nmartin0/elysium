"""
Which configuration is this? -- step 1a of HOT_RELOAD_PLAN.md.

Elysium reads its four config files once at startup, and until now
nothing could say WHICH configuration was in force for a given audit
entry or pending write, because there had only ever been one. That
stops being true when configuration can be reloaded while running, and
it is already not quite true: a restart with edited files produces a
second configuration the log cannot distinguish from the first.

Identity only. Nothing reloads yet.
"""

from datetime import UTC, datetime
from pathlib import Path

from core.deployment_loader import CONFIG_FILENAMES, _source_digest, load_deployment

DEPLOYMENT = Path(__file__).resolve().parent.parent.parent / "deployment" / "etc"


def test_the_same_files_produce_the_same_digest(tmp_path):
    # The property the whole mechanism rests on: unchanged files are
    # recognisably unchanged. Without this, every reload would look
    # like a change.
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text(f"# {name}\nkey: value\n")

    assert _source_digest(tmp_path, CONFIG_FILENAMES) == _source_digest(tmp_path, CONFIG_FILENAMES)


def test_changing_any_one_file_changes_the_digest(tmp_path):
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text("key: value\n")
    before = _source_digest(tmp_path, CONFIG_FILENAMES)

    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text("key: CHANGED\n")
        assert _source_digest(tmp_path, CONFIG_FILENAMES) != before, f"{name} went unnoticed"
        (tmp_path / name).write_text("key: value\n")


def test_a_comment_change_changes_the_digest(tmp_path):
    # Over the RAW BYTES, not the parsed structures, deliberately. The
    # question is "are these the same files", not "do they mean the
    # same thing" -- comparing parsed dicts would call a comment change
    # identical, and a key reordering different, both backwards here.
    for name in CONFIG_FILENAMES:
        (tmp_path / name).write_text("key: value\n")
    before = _source_digest(tmp_path, CONFIG_FILENAMES)
    (tmp_path / CONFIG_FILENAMES[0]).write_text("# a note\nkey: value\n")

    assert _source_digest(tmp_path, CONFIG_FILENAMES) != before


def test_moving_text_between_files_changes_the_digest(tmp_path):
    # Each file's NAME is fed in alongside its content for this reason.
    # Hashing concatenated content alone would call these identical.
    (tmp_path / CONFIG_FILENAMES[0]).write_text("a: 1\nb: 2\n")
    (tmp_path / CONFIG_FILENAMES[1]).write_text("")
    before = _source_digest(tmp_path, CONFIG_FILENAMES)

    (tmp_path / CONFIG_FILENAMES[0]).write_text("a: 1\n")
    (tmp_path / CONFIG_FILENAMES[1]).write_text("b: 2\n")

    assert _source_digest(tmp_path, CONFIG_FILENAMES) != before


def test_a_missing_file_does_not_raise(tmp_path):
    # load_deployment() reports a missing file far better than a hash
    # function could. This must not become a second, worse place that
    # error surfaces.
    _source_digest(tmp_path, CONFIG_FILENAMES)


def test_each_load_gets_its_own_generation_number():
    # Assigned by the loader, never by a caller, so two callers cannot
    # mint the same number.
    first = load_deployment(DEPLOYMENT)
    second = load_deployment(DEPLOYMENT)

    assert second.generation > first.generation


def test_two_loads_of_unchanged_files_share_a_digest_but_not_a_generation():
    # The distinction that matters: the digest says WHAT was read, the
    # generation says WHICH READ it was. A reload of unchanged files is
    # a new generation of the same configuration, and conflating the
    # two would make "did anything change?" unanswerable.
    first = load_deployment(DEPLOYMENT)
    second = load_deployment(DEPLOYMENT)

    assert first.source_digest == second.source_digest
    assert first.generation != second.generation


def test_loaded_at_is_an_aware_utc_instant():
    # Aware, not naive: this timestamp is compared against audit entries
    # across a deployment, and a naive one silently means "whatever the
    # server's local zone was".
    before = datetime.now(UTC)
    config = load_deployment(DEPLOYMENT)

    assert config.loaded_at.tzinfo is not None
    assert before <= config.loaded_at <= datetime.now(UTC)


# --- the generation reaching the durable records ---
#
# Step 1a gave a configuration load an identity. This is the half that
# makes it useful: the identity has to reach the things that OUTLIVE
# the load, or it answers nothing.

import json  # noqa: E402

import pytest  # noqa: E402

from core.intermediate_layer.audit import AuditLog  # noqa: E402
from tests.unit.test_named_actions import _record, write_mediator  # noqa: E402,F401


def test_every_audit_entry_carries_the_generation(tmp_path):
    # Stamped in _write(), the one place every entry passes through, so
    # a new kind of entry added later cannot be the one that forgets.
    log = AuditLog(tmp_path / "audit.log", generation=7)
    log.log_access("alice", "Customer", "c1", "read", mac_allowed=True, rbac_allowed=True)

    entry = json.loads((tmp_path / "audit.log").read_text().splitlines()[0])
    assert entry["generation"] == 7


def test_an_audit_log_with_no_generation_omits_the_field(tmp_path):
    # None means "not recorded", not zero. DataMediator and
    # PendingWriteStore each default a bare AuditLog for tests, and
    # they genuinely have no generation to name -- a 0 or -1 would be a
    # value that looks like an answer.
    log = AuditLog(tmp_path / "audit.log")
    log.log_access("alice", "Customer", "c1", "read", mac_allowed=True, rbac_allowed=True)

    entry = json.loads((tmp_path / "audit.log").read_text().splitlines()[0])
    assert "generation" not in entry


def test_a_pending_write_records_the_generation_that_authorized_it(write_mediator):  # noqa: F811
    # The first thing in Elysium that OUTLIVES the request that made
    # it. Everything else is decided and finished inside one call, so
    # configuration could never change underneath it.
    write_mediator.generation = 42

    pending = write_mediator.propose_action(
        _record("lead"), "ReopenTicket", {"ticket_id": "t1", "reason": "again"}, origin="human",
    )

    assert pending.proposed_under_generation == 42


def test_apply_time_audit_records_the_generation_the_write_was_proposed_under(write_mediator, tmp_path):  # noqa: F811
    # THE POINT OF THE FIELD. The audit log stamps the generation in
    # force when a write is APPLIED; the pending write carries the one
    # it was PROPOSED under. An entry carrying two different numbers is
    # a write that outlived a configuration change -- ordinary once an
    # approvals inbox exists, and currently undetectable.
    write_mediator.generation = 3
    write_mediator.mediator.audit_log = AuditLog(tmp_path / "audit.log", generation=3)

    pending = write_mediator.propose_action(
        _record("lead"), "ReopenTicket", {"ticket_id": "t1", "reason": "again"}, origin="human",
    )

    # THE RELOAD. Between proposing and approving, configuration
    # changed: this deployment is now serving generation 4. Simulated
    # by moving both, exactly as rebuilding the bundle will at step 2.
    #
    # Without this the test cannot tell the two generations apart -- a
    # control that replaced pending.proposed_under_generation with
    # self.generation passed, because both were 3.
    write_mediator.generation = 4
    write_mediator.mediator.audit_log = AuditLog(tmp_path / "audit.log", generation=4)

    write_mediator.confirm_and_execute(pending, approved=True)

    # Nested under "params", which is where log_pre() puts the write's
    # own detail -- checked against the code rather than assumed, after
    # a first version of this test asserted the wrong shape and blamed
    # the implementation.
    entries = [json.loads(line) for line in (tmp_path / "audit.log").read_text().splitlines()]
    pre = [e for e in entries if e.get("stage") == "pre"]
    assert pre, "no pre-write audit entry at all"
    assert pre[0]["params"]["proposed_under_generation"] == 3
    assert pre[0]["generation"] == 4, "the applying generation must be recorded too"


def test_the_generation_is_required_on_a_pending_write():
    # No default, for the same reason origin has none: a default would
    # be a guess written into an audit trail.
    from core.ontology.write_mediator import PendingWrite

    with pytest.raises(TypeError):
        PendingWrite((), "alice", "desc", "Act", "human", datetime.now(UTC))
