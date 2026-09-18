"""
Full-stack concurrency tests for the real write path.

WHY THIS FILE EXISTS. tests/unit/test_concurrency.py proves the LOCKING
PRIMITIVES are sound -- KeyedLockManager hands out one lock per key,
sorted acquisition avoids deadlock, ConcurrencyLimiter enforces its
limit. What it does not do is run two genuinely concurrent
confirm_and_execute() calls, with overlapping objects, through the
whole propose -> log -> apply sequence. That was a known, recorded gap
in the deferred list; this closes it.

The distinction matters because the primitives being correct does not
prove the write path USES them correctly. A lock held around the wrong
span, released too early, or taken on the wrong key would leave every
primitive test passing while real concurrent writes lost updates.

WHAT CORRECTNESS LOOKS LIKE HERE, stated precisely because "no crash"
is not the bar: for two concurrent transfers against the same account,
exactly one of two outcomes is acceptable per caller -- the write
lands, or it is REJECTED because the object changed since the value was
read (WriteMediator's own optimistic-concurrency check). What must
never happen is both callers being told they succeeded while only one
change survives: a silently lost update.

Each test repeats across trials. A race needs a specific interleaving,
and a single run passes against broken code often enough to be
worthless -- a lesson learned directly in this project, where a
one-shot concurrency test passed against a genuinely racy LockStore.
"""

import sqlite3
import threading

import pytest
import yaml

from core.deployment_loader import _WRITE_ADAPTER_REGISTRY, _build_adapters
from core.intermediate_layer.auth import UserRecord
from core.ontology.link_types import expand_link_types
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter
from core.ontology.write_mediator import WriteMediator

FIXTURES = "tests/integration/fixtures/"
TRIALS = 15

ACCOUNTANT = UserRecord(user_id="u1", security_value="us-west", role_name="accountant")


def _deployment(tmp_path, trial):
    """A real, isolated deployment: real SQLite database, real adapters,
    real write log, real mediators. Nothing mocked -- the point is to
    exercise the actual write path."""
    schema = yaml.safe_load(open(FIXTURES + "ontology_schema.yaml"))
    # Link fields are GENERATED from link_types at load; the raw
    # YAML no longer declares them (see core/ontology/link_types.py).
    schema["object_types"] = expand_link_types(
        schema.get("link_types", {}), schema["object_types"]
    )
    policy = yaml.safe_load(open(FIXTURES + "policy.yaml"))

    db_path = tmp_path / f"m{trial}.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(open(FIXTURES + "schema.sql").read())
    conn.commit()
    conn.close()

    adapters = _build_adapters(
        {"primary_sql": {"adapter": "sqlite", "connection": {"path": db_path}}},
        _WRITE_ADAPTER_REGISTRY,
    )
    # Account's security chains through Customer (security.via_field:
    # owner_customer_id), so both types must be present or every MAC
    # check raises -- a real constraint of this fixture ontology, not a
    # test convenience.
    object_types = {
        name: type_def
        for name, type_def in schema["object_types"].items()
        if name in ("Account", "Customer")
    }
    mediator = DataMediator(
        object_types,
        adapters,
        dict.fromkeys(object_types, "primary_sql"),
        policy["roles"],
        write_log=WriteLogWriter(tmp_path / f"wl{trial}.db"),
    )
    write_mediator = WriteMediator(
        mediator, adapters, policy["roles"], schema["action_types"], generation=1)
    return mediator, write_mediator


def _run_together(fns):
    """Runs each fn in its own thread, forced past a barrier together so
    they genuinely contend rather than relying on lucky timing."""
    barrier = threading.Barrier(len(fns))
    results = []
    guard = threading.Lock()

    def worker(fn):
        barrier.wait()
        try:
            outcome = fn()
        except Exception as exc:
            outcome = f"REJECTED:{type(exc).__name__}"
        with guard:
            results.append(outcome)

    threads = [threading.Thread(target=worker, args=(fn,)) for fn in fns]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _transfer(write_mediator, new_from_balance):
    """Proposes a real TransferFunds, returning a callable that confirms
    it. Proposal happens BEFORE the barrier so both callers hold a
    pending write built against the same pre-state -- which is exactly
    the situation the optimistic-concurrency check exists for."""
    pending = write_mediator.propose_action(
        ACCOUNTANT,
        "TransferFunds",
        {
            "from_account_id": "acc_checking",
            "to_account_id": "acc_savings",
            "new_from_balance": new_from_balance,
            "new_to_balance": 600,
        }, origin="human")
    return lambda: write_mediator.confirm_and_execute(pending, approved=True)


@pytest.mark.parametrize("trial", range(TRIALS))
def test_two_concurrent_writes_to_one_account_never_lose_an_update(tmp_path, trial):
    # THE gap this file exists to close. Both callers propose against
    # the same pre-state, then confirm simultaneously.
    mediator, write_mediator = _deployment(tmp_path, trial)

    results = _run_together(
        [_transfer(write_mediator, 100), _transfer(write_mediator, 200)]
    )

    written = [r for r in results if isinstance(r, dict)]
    rejected = [r for r in results if isinstance(r, str)]

    # Exactly one may win. The other must be REJECTED, not silently
    # dropped -- being told "written" while your change vanished is the
    # actual failure mode.
    assert len(written) == 1, f"expected one winner, got {results}"
    assert len(rejected) == 1, f"expected one rejection, got {results}"

    # And the surviving value is genuinely one of the two proposed --
    # never a torn mix.
    final = mediator.get_field(ACCOUNTANT, "Account", "acc_checking", "balance")
    assert final in (100, 200), f"final balance {final!r} matches neither write"


@pytest.mark.parametrize("trial", range(TRIALS))
def test_the_winning_write_lands_on_every_object_it_touches(tmp_path, trial):
    # TransferFunds is a multi-object action. A partially-applied batch
    # -- one account updated, the other not -- would be a genuine
    # atomicity failure, and concurrency is where that would surface.
    mediator, write_mediator = _deployment(tmp_path, trial)

    _run_together([_transfer(write_mediator, 100), _transfer(write_mediator, 200)])

    from_balance = mediator.get_field(ACCOUNTANT, "Account", "acc_checking", "balance")
    to_balance = mediator.get_field(ACCOUNTANT, "Account", "acc_savings", "balance")

    # Whichever transfer won, BOTH of its sub-writes must have applied.
    assert from_balance in (100, 200)
    assert to_balance == 600, "the second sub-write did not apply"


@pytest.mark.parametrize("trial", range(TRIALS))
def test_concurrent_writes_leave_no_pending_entries_behind(tmp_path, trial):
    # A write log entry left pending after both callers finished would
    # mean crash recovery re-applies it on next startup -- a real,
    # delayed corruption rather than an immediate one.
    _mediator, write_mediator = _deployment(tmp_path, trial)

    _run_together([_transfer(write_mediator, 100), _transfer(write_mediator, 200)])

    assert write_mediator.write_log.get_pending_batches() == []
    assert write_mediator.write_log.get_all_pending_writes() == []


@pytest.mark.parametrize("trial", range(TRIALS))
def test_concurrent_writes_to_different_objects_both_succeed(tmp_path, trial):
    # The other half: contention must not be over-serialized either. Two
    # writes touching genuinely disjoint objects have no reason to
    # conflict, and both should land.
    mediator, write_mediator = _deployment(tmp_path, trial)

    def rename(customer_id, name):
        pending = write_mediator.propose_action(
            UserRecord(user_id="u1", security_value="us-west", role_name="editor"),
            "UpdateCustomerName",
            {"customer_id": customer_id, "new_name": name}, origin="human")
        return lambda: write_mediator.confirm_and_execute(pending, approved=True)

    results = _run_together([rename("cust_001", "Ada X"), rename("cust_002", "Bram Y")])

    assert all(isinstance(r, dict) for r in results), f"both should land, got {results}"
    editor = UserRecord(user_id="u1", security_value="us-west", role_name="editor")
    assert mediator.get_field(editor, "Customer", "cust_001", "name") == "Ada X"
    assert mediator.get_field(editor, "Customer", "cust_002", "name") == "Bram Y"


def test_the_keyed_lock_manager_hands_out_one_lock_under_real_contention():
    # KeyedLockManager relies on dict.setdefault() being atomic. That
    # claim is load-bearing -- every per-object write lock depends on
    # concurrent callers receiving the SAME lock object -- so it is
    # verified directly rather than trusted.
    from core.concurrency import KeyedLockManager

    for _ in range(20):
        manager = KeyedLockManager()
        seen = []
        guard = threading.Lock()
        barrier = threading.Barrier(16)

        def grab(barrier=barrier, manager=manager, guard=guard, seen=seen):
            barrier.wait()
            lock = manager.lock_for(("Account", "acc_1"))
            with guard:
                seen.append(id(lock))

        threads = [threading.Thread(target=grab) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(seen)) == 1, "concurrent callers received different locks"
