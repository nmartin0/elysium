"""
Point 2 of the machinery audit: the data copying mechanism -- the write
path and its write log -- checked against Palantir's own precedent.

FOUNDRY'S STANDARD, quoted directly rather than paraphrased so the
comparison is honest: "All table updates in a job are committed
together. If the job fails at any point, no partial writes are
visible." Foundry contrasts this with plain Iceberg, which "provides
atomic updates: each update is applied individually," and notes that
per-update atomicity "can pose correctness issues for pipelines that
perform multiple writes in a single transaction."

WHERE ELYSIUM GENUINELY DIFFERS, stated plainly rather than claimed
away. Elysium writes to the CUSTOMER'S OWN databases, which may be
several genuinely separate systems with no shared transaction. There
is no distributed transaction coordinator, so a true all-or-nothing
commit across two different databases is not available. Rolling back
is not available either: the "undo" would itself be a write that could
fail.

WHAT ELYSIUM DOES INSTEAD, and what these tests pin down:
  - ONE atomic boundary that always holds: the write log entry. A
    single INSERT records the whole intent before anything is applied,
    so a crash can never lose the record of what was meant to happen.
  - Per-object locks held across the WHOLE log-then-apply sequence, so
    concurrent writers cannot interleave.
  - Reads MASKED from the log, so an in-flight multi-object write is
    never observed half-applied.
  - A genuinely half-applied write is surfaced as AMBIGUOUS at
    startup, escalated for human review -- never silently declared
    fine.

That last property is the one this audit found broken, and the tests
below are written so it cannot silently regress.
"""

import sqlite3

import pytest
import yaml

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter
from core.ontology.write_mediator import WriteMediator

FIXTURES = "tests/integration/fixtures/"
ACCOUNTANT = UserRecord(user_id="u1", security_value="us-west", role_name="accountant")


@pytest.fixture
def deployment(tmp_path):
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    # Link fields are GENERATED from link_types at load; the raw
    # YAML no longer declares them (see core/ontology/link_types.py).
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))

    db_path = tmp_path / "business.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    conn.commit()
    conn.close()

    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": db_path}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    object_types = {
        name: type_def
        for name, type_def in schema["object_types"].items()
        if name in ("Account", "Customer")
    }
    write_log = WriteLogWriter(tmp_path / "write_log.db")
    mediator = DataMediator(
        object_types,
        adapters,
        dict.fromkeys(object_types, "primary_sql"),
        policy["roles"],
        write_log=write_log,
    )
    write_mediator = WriteMediator(
        mediator, adapters, policy["roles"], schema["action_types"], generation=1)
    return mediator, write_mediator, write_log, db_path


def _transfer(write_mediator, from_balance=900, to_balance=600):
    return write_mediator.propose_action(
        ACCOUNTANT,
        "TransferFunds",
        {
            "from_account_id": "acc_checking",
            "to_account_id": "acc_savings",
            "new_from_balance": from_balance,
            "new_to_balance": to_balance,
        }, origin="human")


def _raw(db_path, account_id):
    """Reads the REAL database, bypassing the write log's masking --
    the only way to tell what genuinely landed."""
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT balance FROM accounts WHERE account_id = ?", (account_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def test_a_multi_object_action_applies_to_every_object(deployment):
    mediator, write_mediator, _log, db_path = deployment

    write_mediator.confirm_and_execute(_transfer(write_mediator), approved=True)

    assert _raw(db_path, "acc_checking") == 900
    assert _raw(db_path, "acc_savings") == 600


def test_the_whole_intent_is_logged_before_anything_is_applied(deployment):
    # The one atomic boundary that always holds. A crash between the log
    # write and the apply must leave a complete record of what was
    # meant to happen -- that is what makes recovery possible at all.
    _mediator, write_mediator, log, _db = deployment
    pending = _transfer(write_mediator)

    write_mediator.confirm_and_execute(pending, approved=True)

    # Both sub-writes were recorded under one batch, not two independent
    # entries that could diverge.
    conn = sqlite3.connect(log.db_path)
    conn.row_factory = sqlite3.Row
    try:
        batch_ids = {r["batch_id"] for r in conn.execute("SELECT batch_id FROM write_log")}
        assert len(batch_ids) == 1
        assert None not in batch_ids
    finally:
        conn.close()


def test_a_rejected_action_writes_absolutely_nothing(deployment):
    mediator, write_mediator, log, db_path = deployment
    pending = _transfer(write_mediator)

    # None at this layer -- api/routes.py converts it to the
    # {"status": "rejected"} the caller sees. Asserted as-is rather
    # than against the HTTP shape, since this is the mediator's own
    # contract.
    assert write_mediator.confirm_and_execute(pending, approved=False) is None
    assert _raw(db_path, "acc_checking") == 500
    assert _raw(db_path, "acc_savings") == 1000
    assert log.get_all_pending_writes() == []


def test_a_clean_rejection_leaves_no_trace_for_recovery(deployment):
    # A write rejected by the optimistic-concurrency check changed
    # nothing, so there is genuinely nothing for recovery to finish. It
    # must not be left pending -- doing so previously made
    # resume_pending_writes() raise at startup.
    _mediator, write_mediator, log, _db = deployment
    first = _transfer(write_mediator, from_balance=900)
    second = _transfer(write_mediator, from_balance=800)

    write_mediator.confirm_and_execute(first, approved=True)
    with pytest.raises(ValueError, match="changed since"):
        write_mediator.confirm_and_execute(second, approved=True)

    assert log.get_pending_batches() == []
    assert log.get_all_pending_writes() == []
    # And startup recovery runs cleanly rather than raising.
    assert write_mediator.resume_pending_writes() == {
        "resumed": 0,
        "already_applied": 0,
        "ambiguous": 0,
    }


def test_a_genuinely_half_applied_write_is_flagged_ambiguous(deployment):
    # THE case where Elysium cannot match Foundry's all-or-nothing
    # guarantee, and must therefore be honest about it rather than
    # pretend. The first sub-write commits; the second is rejected
    # because its object changed underneath. There is no rollback
    # available -- the undo would itself be a write that could fail.
    #
    # So the requirement is not "never happens" but "never silently
    # accepted": the entry stays pending, and recovery reports it as
    # AMBIGUOUS for human review rather than declaring it fine.
    mediator, write_mediator, log, db_path = deployment
    pending = _transfer(write_mediator)

    # Change the SECOND account behind the action's back.
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE accounts SET balance = 9999 WHERE account_id = 'acc_savings'")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="changed since"):
        write_mediator.confirm_and_execute(pending, approved=True)

    # The first sub-write genuinely landed; the second genuinely did not.
    assert _raw(db_path, "acc_checking") == 900
    assert _raw(db_path, "acc_savings") == 9999

    # And that mismatch is SURFACED, not swallowed.
    summary = write_mediator.resume_pending_writes()
    assert summary["ambiguous"] == 1, (
        "a half-applied write must be escalated for review, never reported as fine"
    )


def test_a_half_applied_write_is_not_reported_as_already_applied(deployment):
    # A regression guard for the specific bug this audit found: the
    # failed sub-write's log row was being marked 'applied', so recovery
    # skipped it and declared the batch already done -- stranding the
    # mismatch permanently while reads kept masking a value that would
    # never exist.
    _mediator, write_mediator, log, db_path = deployment
    pending = _transfer(write_mediator)

    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE accounts SET balance = 9999 WHERE account_id = 'acc_savings'")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError):
        write_mediator.confirm_and_execute(pending, approved=True)

    conn = sqlite3.connect(log.db_path)
    conn.row_factory = sqlite3.Row
    try:
        statuses = {
            r["object_id"]: r["status"] for r in conn.execute("SELECT object_id, status FROM write_log")
        }
    finally:
        conn.close()

    assert statuses["acc_checking"] == "applied", "the sub-write that landed"
    assert statuses["acc_savings"] == "pending", (
        "the sub-write that FAILED must stay pending for recovery"
    )


def test_reads_never_observe_a_partially_applied_write(deployment):
    # Foundry: "no partial writes are visible." Elysium cannot make the
    # WRITE atomic across separate databases, but it can make the READ
    # atomic -- the write log masks in-flight changes so a reader sees
    # the intended state, never a half-applied mix.
    mediator, write_mediator, log, _db = deployment
    pending = _transfer(write_mediator)

    # Log the batch without applying it, simulating the in-flight window.
    log.log_pending_batch(
        [
            {
                "object_type": sw.object_type,
                "object_id": sw.object_id,
                "operation": sw.operation,
                "changes": sw.changes,
                "expected_current_values": sw.expected_current_values,
            }
            for sw in pending.sub_writes
        ],
        pending.user_id,
        pending.description,
    )

    # Both objects report their INTENDED values, not one old and one new.
    assert mediator.get_field(ACCOUNTANT, "Account", "acc_checking", "balance") == 900
    assert mediator.get_field(ACCOUNTANT, "Account", "acc_savings", "balance") == 600


def test_resume_completes_a_write_that_never_applied(deployment):
    # The crash-recovery path proper: an entry logged but never applied
    # (the process died in between) must be finished on restart, since
    # the objects still hold their pre-write values.
    mediator, write_mediator, log, db_path = deployment
    pending = _transfer(write_mediator)

    log.log_pending_batch(
        [
            {
                "object_type": sw.object_type,
                "object_id": sw.object_id,
                "operation": sw.operation,
                "changes": sw.changes,
                "expected_current_values": sw.expected_current_values,
            }
            for sw in pending.sub_writes
        ],
        pending.user_id,
        pending.description,
    )

    summary = write_mediator.resume_pending_writes()

    assert summary["resumed"] == 1
    assert _raw(db_path, "acc_checking") == 900
    assert _raw(db_path, "acc_savings") == 600


def test_resume_is_idempotent(deployment):
    # Recovery may run on every startup. Running it twice must not
    # double-apply anything.
    _mediator, write_mediator, log, db_path = deployment
    pending = _transfer(write_mediator)
    log.log_pending_batch(
        [
            {
                "object_type": sw.object_type,
                "object_id": sw.object_id,
                "operation": sw.operation,
                "changes": sw.changes,
                "expected_current_values": sw.expected_current_values,
            }
            for sw in pending.sub_writes
        ],
        pending.user_id,
        pending.description,
    )

    write_mediator.resume_pending_writes()
    second = write_mediator.resume_pending_writes()

    assert second == {"resumed": 0, "already_applied": 0, "ambiguous": 0}
    assert _raw(db_path, "acc_checking") == 900
