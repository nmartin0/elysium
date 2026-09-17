"""
One reviewer, one task, one decision.

FOUNDRY SEPARATES APPROVAL FROM INVOCATION, and that dissolves what
looked like a trade-off. Approval is per task and partial by
eligibility -- "approve or reject all tasks in the request THAT YOU
ARE ELIGIBLE TO REVIEW" -- while invocation is not: "all tasks
associated with a request must be approved for the request to be
invoked".

So a reviewer approves the tasks they can, the rest wait, and nothing
applies until every task is approved. Partial APPROVAL, atomic
EXECUTION.

A TASK IS ONE SUB-WRITE. A bulk action naming fifty objects is fifty
tasks, and a reviewer may be eligible for some and not others.

THIS FILE COVERS THE RECORDS ONLY -- step 1 of four. Nothing here
gates invocation yet; confirm_and_execute still takes one decision
from one person. That is deliberate: the records have to exist and be
trustworthy before anything depends on them.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite
from core.pending_write_store import PendingWriteStore


def _pending(task_count: int) -> PendingWrite:
    return PendingWrite(
        sub_writes=tuple(
            SubWrite(object_type="Thing", object_id=str(n), operation="update",
                     changes={"a": n})
            for n in range(task_count)
        ),
        user_id="proposer",
        description=f"{task_count} task(s)",
        action_type_name="DoThing",
        origin="human",
        proposed_at=datetime.now(UTC),
        proposed_under_generation=1,
        parameters={},
        # THE PROPOSER AS A RECORD, not just a user_id: a submission
        # criterion may compare against any of their attributes, and
        # four-eyes compares against who proposed it.
        proposer=UserRecord("proposer", "us-west", "customer_service"),
    )


@pytest.fixture
def store():
    return PendingWriteStore()


class TestRecording:
    def test_a_decision_is_recorded_against_its_task(self, store):
        write_id = store.store(_pending(3))

        assert store.record_task_decision(write_id, 1, "alice", approved=True)

        decisions = store.task_decisions(write_id)
        assert list(decisions) == [1]
        assert decisions[1].approver_user_id == "alice"

    def test_reviewers_decide_independently(self, store):
        """THE POINT OF THE WHOLE DESIGN. Three roles signing off on
        one request is three decisions on three tasks, and the request
        waits for all of them."""
        write_id = store.store(_pending(3))

        store.record_task_decision(write_id, 0, "alice", approved=True)
        store.record_task_decision(write_id, 1, "bob", approved=True)

        decisions = store.task_decisions(write_id)
        assert decisions[0].approver_user_id == "alice"
        assert decisions[1].approver_user_id == "bob"

    def test_a_reviewer_may_change_their_mind(self, store):
        # Before invocation, a misclick should not be permanent.
        write_id = store.store(_pending(1))

        store.record_task_decision(write_id, 0, "alice", approved=True)
        store.record_task_decision(write_id, 0, "alice", approved=False)

        assert store.task_decisions(write_id)[0].approved is False

    def test_a_rejection_is_recorded_rather_than_discarded(self, store):
        """A rejected task blocks invocation the same way an undecided
        one does. Deleting the write instead would throw away who
        rejected it and why it never ran."""
        write_id = store.store(_pending(2))

        store.record_task_decision(write_id, 0, "alice", approved=False)

        assert store.task_decisions(write_id)[0].approved is False
        assert store.is_fully_approved(write_id) is False

    def test_deciding_on_a_vanished_write_reports_rather_than_raises(self, store):
        # A write can expire between a reviewer opening their inbox and
        # deciding. That is a race, not an error.
        assert store.record_task_decision("no-such-write", 0, "alice", approved=True) is False

    def test_an_out_of_range_task_is_loud(self, store):
        # A reviewer cannot produce this; only code miscounting tasks
        # can, so it must not pass quietly.
        write_id = store.store(_pending(2))

        with pytest.raises(IndexError):
            store.record_task_decision(write_id, 5, "alice", approved=True)


class TestTheInvocationGate:
    def test_every_task_approved_means_ready(self, store):
        write_id = store.store(_pending(3))
        for index in range(3):
            store.record_task_decision(write_id, index, "alice", approved=True)

        assert store.is_fully_approved(write_id) is True

    def test_one_task_undecided_means_not_ready(self, store):
        """FOUNDRY'S RULE, and the reason partial approval is safe:
        "all tasks associated with a request must be approved for the
        request to be invoked"."""
        write_id = store.store(_pending(3))
        store.record_task_decision(write_id, 0, "alice", approved=True)
        store.record_task_decision(write_id, 1, "alice", approved=True)

        assert store.is_fully_approved(write_id) is False

    def test_one_task_rejected_means_not_ready(self, store):
        write_id = store.store(_pending(2))
        store.record_task_decision(write_id, 0, "alice", approved=True)
        store.record_task_decision(write_id, 1, "bob", approved=False)

        assert store.is_fully_approved(write_id) is False

    def test_an_unknown_write_is_not_approved(self, store):
        # THE CONTROL on the gate's direction. A write that expired
        # between the last approval and this check must not read as
        # ready -- defaulting to True here would invoke a write nobody
        # can see.
        assert store.is_fully_approved("no-such-write") is False

    def test_an_expired_write_is_not_approved(self, store):
        store_with_no_ttl = PendingWriteStore(ttl=timedelta(seconds=-1))
        write_id = store_with_no_ttl.store(_pending(1))
        store_with_no_ttl.record_task_decision(write_id, 0, "alice", approved=True)

        assert store_with_no_ttl.is_fully_approved(write_id) is False


def test_decisions_are_a_copy(store):
    # A caller iterating must not be surprised by another reviewer
    # deciding mid-loop, and must not be able to mutate the store.
    write_id = store.store(_pending(2))
    store.record_task_decision(write_id, 0, "alice", approved=True)

    snapshot = store.task_decisions(write_id)
    snapshot[1] = snapshot[0]

    assert list(store.task_decisions(write_id)) == [0]


class TestTheGateHoldsARequestOpen:
    """What the gate does once eligibility exists.

    Today every reviewer can decide every task, so a single confirm
    records all of them and the gate opens immediately -- behaviour is
    unchanged, which the integration suite confirms. These tests drive
    the store directly to show the gate holding a request that is only
    PARTLY approved, which is the state step 3 will make reachable.
    """

    def test_a_request_waits_for_the_tasks_nobody_has_decided(self, store):
        write_id = store.store(_pending(3))
        store.record_task_decision(write_id, 0, "alice", approved=True)

        assert store.is_fully_approved(write_id) is False

    def test_it_opens_when_the_last_reviewer_decides(self, store):
        """THE MULTI-APPROVER CASE, which is the whole point: three
        roles each signing off, and nothing running until all three
        have."""
        write_id = store.store(_pending(3))

        store.record_task_decision(write_id, 0, "alice", approved=True)
        assert store.is_fully_approved(write_id) is False

        store.record_task_decision(write_id, 1, "bob", approved=True)
        assert store.is_fully_approved(write_id) is False

        store.record_task_decision(write_id, 2, "carol", approved=True)
        assert store.is_fully_approved(write_id) is True

    def test_one_rejection_holds_the_request_shut_permanently(self, store):
        # Not "until someone else approves": the rejection stays
        # recorded, so the request never becomes whole unless that
        # reviewer changes their own decision.
        write_id = store.store(_pending(2))
        store.record_task_decision(write_id, 0, "alice", approved=True)
        store.record_task_decision(write_id, 1, "bob", approved=False)

        assert store.is_fully_approved(write_id) is False

        store.record_task_decision(write_id, 1, "bob", approved=True)
        assert store.is_fully_approved(write_id) is True

    def test_a_single_task_request_needs_exactly_one_decision(self, store):
        # THE COMMON CASE, and the one that must not regress: most
        # writes are one task and should behave exactly as before.
        write_id = store.store(_pending(1))

        assert store.is_fully_approved(write_id) is False
        store.record_task_decision(write_id, 0, "alice", approved=True)
        assert store.is_fully_approved(write_id) is True
