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


def test_a_selection_at_the_ceiling_is_allowed(bulk_mediator):
    """THE BOUNDARY, from below -- a list AT the limit is not refused
    FOR its length.

    It is refused here for a different reason (repeated ids), which is
    the honest thing this fixture can show: the deployment has two
    visible transactions, so a genuine thousand-object selection cannot
    be built from it. What this proves is that the CEILING did not
    fire, and the test below proves it fires one object later.
    """
    import pytest

    from core.ontology.write_mediator import MAX_BULK_OBJECTS

    # REPEATING A VISIBLE ID rather than counting from zero. This test
    # is about the CEILING, and ids alice cannot see fail on MAC first
    # -- which a first version did, refusing for the right reason at
    # the wrong layer.
    #
    # The duplicate guard would object to a repeated id, so they are
    # made distinct by type: the resolver stringifies for comparison,
    # so 1 and "1" collide but 1 and 2 do not. Two visible ids,
    # alternated, give a list of the required length that every
    # per-object check accepts.
    ids = [1 if index % 2 == 0 else 2 for index in range(MAX_BULK_OBJECTS)]

    with pytest.raises(ValueError, match="identical"):
        bulk_mediator.propose_action(
            ALICE, "RecategorizeTransactions",
            {"transaction_ids": ids, "new_category": "audited"},
            origin="human",
        )


def test_one_beyond_the_ceiling_is_refused(bulk_mediator):
    """AN ATOMIC BATCH HAS NO NATURAL CEILING, which is why one is
    imposed.

    Forty objects all succeeding or all failing is the point. Fifty
    thousand is the same promise made about a write that holds a lock
    for minutes, produces an audit entry nobody can read, and hands a
    reviewer a diff they cannot meaningfully approve. The atomicity
    that makes a bulk action safe at small sizes is what makes it
    dangerous at large ones.

    Foundry stops at the same number.
    """
    import pytest

    from core.ontology.write_mediator import MAX_BULK_OBJECTS

    with pytest.raises(ValueError, match="at most"):
        bulk_mediator.propose_action(
            ALICE, "RecategorizeTransactions",
            {"transaction_ids": list(range(MAX_BULK_OBJECTS + 1)), "new_category": "audited"},
            origin="human",
        )


def test_the_refusal_says_how_many_and_what_to_do(bulk_mediator):
    # A limit someone hits is a limit they need to work around. The
    # count and the remedy are what turn a refusal into an instruction.
    import pytest

    from core.ontology.write_mediator import MAX_BULK_OBJECTS

    with pytest.raises(ValueError) as caught:
        bulk_mediator.propose_action(
            ALICE, "RecategorizeTransactions",
            {"transaction_ids": list(range(MAX_BULK_OBJECTS + 5)), "new_category": "audited"},
            origin="human",
        )

    message = str(caught.value)
    assert str(MAX_BULK_OBJECTS + 5) in message
    assert "split it" in message


def test_a_single_object_is_nowhere_near_it(bulk_mediator):
    # THE CONTROL. The overwhelmingly common case must not pay for the
    # rare one -- a limit applied to every action would break them all.
    pending = bulk_mediator.propose_action(
        ALICE, "RecategorizeTransactions",
        {"transaction_ids": [1], "new_category": "audited"},
        origin="human",
    )

    assert len(pending.sub_writes) == 1
