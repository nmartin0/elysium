"""One reviewer cannot approve over another's rejection (SEC-13).

FOUND READING pending_write_store.py, not from any audit row.

`record_task_decision` used `INSERT OR REPLACE` keyed on
(write_id, task_index). A second reviewer approving a task a first had
rejected replaced the row, and the refusal vanished -- reviewer
shopping, with no trace that anyone had objected. Measured before
fixing:

    A rejects  -> fully_approved=False, record: approver_a
    B approves -> fully_approved=True,  record: approver_b

LATENT, NOT LIVE, and that is stated plainly rather than dressed up as
worse than it is. The route consumes the write on any rejection -- it
falls through to confirm_and_execute(approved=False) inside
`reserved()`, whose clean exit deletes the write AND its decisions --
so no rejected write survives today for a second reviewer to find.

IT IS CLOSED AT THE STORE ANYWAY, because the store is what a future
partial-rejection feature would call. Foundry scopes a decision to
"all tasks in the request that you are eligible to review", which is
exactly the shape that leaves a rejected task sitting beside undecided
ones -- and this project already implements the approval half of that
scoping.

AND THE DOCSTRING WAS WRONG IN A SECOND WAY. It said this path "keeps
the record of who said no". These rows are deleted with the write,
both on expiry and on consumption: the table is the STATE OF AN OPEN
REQUEST, not the history of one. The durable record is the audit log.
Corrected in the same change.
"""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore


@pytest.fixture
def store_and_write():
    store = PendingWriteStore(
        persistence=PendingWritePersistence(Path(tempfile.mkdtemp()) / "pending.db"),
    )
    pending = PendingWrite(
        sub_writes=(SubWrite("Customer", "c1", "update", {"name": "Ada"}, {"name": "Old"}),),
        user_id="proposer",
        description="rename c1",
        action_type_name="Rename",
        origin="api",
        proposed_at=datetime.now(UTC),
        proposed_under_generation=1,
        parameters={},
        proposer=UserRecord(user_id="proposer", security_value="us-west", role_name="agent"),
    )
    return store, store.store(pending)


class TestARefusalStands:
    def test_another_reviewer_cannot_approve_over_a_rejection(self, store_and_write):
        store, write_id = store_and_write
        store.record_task_decision(write_id, 0, "approver_a", approved=False)

        with pytest.raises(PermissionError):
            store.record_task_decision(write_id, 0, "approver_b", approved=True)

    def test_and_the_write_is_still_not_approved(self, store_and_write):
        """The point of the guard, not just that it raises."""
        store, write_id = store_and_write
        store.record_task_decision(write_id, 0, "approver_a", approved=False)

        with pytest.raises(PermissionError):
            store.record_task_decision(write_id, 0, "approver_b", approved=True)

        assert store.is_fully_approved(write_id) is False
        assert store.task_decisions(write_id)[0].approver_user_id == "approver_a"

    def test_the_refusal_names_who_rejected_it(self, store_and_write):
        store, write_id = store_and_write
        store.record_task_decision(write_id, 0, "approver_a", approved=False)

        with pytest.raises(PermissionError) as raised:
            store.record_task_decision(write_id, 0, "approver_b", approved=True)

        assert "approver_a" in str(raised.value)


class TestWhatMustStillWork:
    """THE OPPOSITE DIRECTION. A guard that froze the first decision
    would make a mistaken click permanent and block every rejection
    after an approval."""

    def test_a_reviewer_may_change_their_own_mind(self, store_and_write):
        store, write_id = store_and_write
        store.record_task_decision(write_id, 0, "approver_a", approved=False)

        store.record_task_decision(write_id, 0, "approver_a", approved=True)

        assert store.is_fully_approved(write_id) is True

    def test_a_rejection_may_always_land(self, store_and_write):
        """Rejecting over somebody else's approval is the FAIL-SAFE
        direction and must never be blocked."""
        store, write_id = store_and_write
        store.record_task_decision(write_id, 0, "approver_a", approved=True)

        store.record_task_decision(write_id, 0, "approver_b", approved=False)

        assert store.is_fully_approved(write_id) is False

    def test_a_first_decision_is_recorded_normally(self, store_and_write):
        store, write_id = store_and_write

        assert store.record_task_decision(write_id, 0, "approver_a", approved=True) is True
        assert store.is_fully_approved(write_id) is True

    def test_a_vanished_write_still_returns_false_rather_than_raising(self, store_and_write):
        """An expired write between opening an inbox and deciding is an
        ordinary race, not an error -- unchanged by this guard."""
        store, _ = store_and_write

        assert store.record_task_decision("no-such-write", 0, "approver_a", approved=True) is False
