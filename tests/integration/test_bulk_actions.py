"""
One action, many objects.

FOUNDRY DRAWS THE LINE IN THE ONTOLOGY, not the UI: a "bulk action
type" is one "using an object reference list parameter". Bulk is a
property of the ACTION, declared and reviewable before anyone runs it,
rather than a mode an application switches into.

So `object_reference_list` is a parameter type, and a sub_write whose
object_id resolves to a list expands into one sub-write per object.

EVERY PER-OBJECT CHECK STILL RUNS. Authorization, submission criteria
and the duplicate guard are all inside the expansion loop -- nothing is
skipped because there are many. A bulk action that authorized once and
wrote forty times would be a privilege escalation wearing a convenience
label.

STILL ONE ATOMIC BATCH. Forty objects means forty writes that all
succeed or all fail, which is what makes a bulk action safe to approve
as a unit: a half-applied bulk edit is the state nobody can reason
about.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import WriteMediator

ALICE = UserRecord("alice", "us-west", "customer_service")


@pytest.fixture
def bulk_mediator(mediator, write_adapters, deployment):
    """A write mediator whose action types include a BULK one.

    Declared here rather than in the shipped deployment: the deployment
    has no bulk action yet, and adding one to it would be a product
    decision made by a test. What is being checked is that the
    MECHANISM works, not that any particular action exists.
    """
    bulk = {
        **deployment.action_types,
        "RecategorizeTransactions": {
            "affected_object_types": ["Transaction"],
            "parameters": {
                "transaction_ids": {
                    "type": "object_reference_list",
                    "object_type": "Transaction",
                    "required": True,
                },
                "new_category": {"type": "string", "required": True},
            },
            "sub_writes": [{
                "object_type": "Transaction",
                "object_id": "parameter.transaction_ids",
                "operation": "update",
                "mutations": [{"set": {"property": "category", "value": "parameter.new_category"}}],
            }],
        },
    }
    roles = {
        name: {**role, "allowed_actions": frozenset(
            set(role.get("allowed_actions", frozenset()))
            | {"execute:RecategorizeTransactions", "write:Transaction.category"},
        )}
        for name, role in deployment.roles.items()
    }
    return WriteMediator(mediator, write_adapters, roles, bulk, generation=1)


def test_a_list_becomes_one_sub_write_per_object(bulk_mediator):
    pending = bulk_mediator.propose_action(
        ALICE, "RecategorizeTransactions",
        {"transaction_ids": [1, 2], "new_category": "audited"},
        origin="human",
    )

    assert len(pending.sub_writes) == 2
    assert {str(sw.object_id) for sw in pending.sub_writes} == {"1", "2"}


def test_a_single_object_still_works(bulk_mediator):
    # THE CONTROL. Every existing action names one object, and a change
    # that only handled lists would break all of them.
    pending = bulk_mediator.propose_action(
        ALICE, "RecategorizeTransactions",
        {"transaction_ids": [1], "new_category": "audited"},
        origin="human",
    )

    assert len(pending.sub_writes) == 1


def test_each_object_carries_the_same_mutation(bulk_mediator):
    pending = bulk_mediator.propose_action(
        ALICE, "RecategorizeTransactions",
        {"transaction_ids": [1, 2], "new_category": "audited"},
        origin="human",
    )

    for sub_write in pending.sub_writes:
        assert sub_write.changes["category"] == "audited"


def test_an_empty_list_writes_nothing(bulk_mediator):
    # Not an error, and not a no-op that reports success on something
    # else. Selecting nothing and acting is a mistake worth making
    # visibly harmless rather than silently broad.
    pending = bulk_mediator.propose_action(
        ALICE, "RecategorizeTransactions",
        {"transaction_ids": [], "new_category": "audited"},
        origin="human",
    )

    assert pending.sub_writes == ()
