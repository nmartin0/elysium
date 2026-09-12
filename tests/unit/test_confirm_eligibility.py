"""
Who may confirm a pending write.

IT USED TO BE THE PROPOSER, AND ONLY THE PROPOSER -- owner-equality
inside PendingWriteStore.pop(). That made four-eyes unreachable: the
only person who could confirm a write was the one person a four-eyes
rule forbids.

IT IS NOW THE GRANT. Whoever may EXECUTE an action may decide on a
proposal of it. That is a real widening for a deployment declaring no
criteria, and it is the intended model rather than a side effect --
with the opposite policy now EXPRESSIBLE where it was previously
hardcoded:

    check: user
    field: user_id
    operator: equals
    value: proposer.user_id

restores owner-only confirmation for a deployment that wants it.

Worth stating plainly: when this changed, NO TEST NOTICED. Owner-only
was a convention rather than a guarantee, which is why these exist.
"""

from datetime import UTC, datetime

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite
from core.pending_write_store import PendingWriteStore

ALICE = UserRecord("alice", "us-west", "editor")


def _pending(user_id="alice", action="RenameAuthor"):
    return PendingWrite(
        sub_writes=(SubWrite("Author", "auth_001", "update", {"name": "Ada"}, {}),),
        user_id=user_id,
        description="rename",
        action_type_name=action,
        origin="human",
        proposed_at=datetime.now(UTC),
        proposed_under_generation=1,
        parameters={},
        proposer=UserRecord(user_id, "us-west", "editor"),
    )


def _store():
    store = PendingWriteStore()
    write_id = store.store(_pending())
    return store, write_id


class TestClaim:
    def test_an_eligible_caller_gets_the_write(self):
        store, write_id = _store()

        assert store.claim(write_id, lambda _pending: True) is not None

    def test_an_ineligible_caller_gets_nothing(self):
        store, write_id = _store()

        assert store.claim(write_id, lambda _pending: False) is None

    def test_an_ineligible_claim_does_not_consume_the_write(self):
        # THE PROPERTY A REFUSAL MUST HAVE. If a denied claim removed
        # the write, one ineligible request would destroy a proposal
        # somebody else was entitled to approve -- a denial-of-service
        # available to anyone who can guess an id.
        store, write_id = _store()

        store.claim(write_id, lambda _pending: False)

        assert store.claim(write_id, lambda _pending: True) is not None

    def test_a_second_claim_finds_nothing(self):
        # ATOMICITY. Two approvers must not both claim one write, or
        # the second applies a change that was already applied.
        store, write_id = _store()

        assert store.claim(write_id, lambda _pending: True) is not None
        assert store.claim(write_id, lambda _pending: True) is None

    def test_the_predicate_sees_the_write_it_is_deciding_about(self):
        # The grant check needs the action type, so the predicate is
        # given the write rather than just its id.
        store, write_id = _store()
        seen = []

        store.claim(write_id, lambda pending: seen.append(pending.action_type_name) or True)

        assert seen == ["RenameAuthor"]

    def test_an_unknown_id_is_indistinguishable_from_an_ineligible_one(self):
        # UNIFORM DENIAL, kept deliberately from the owner-equality
        # version rather than rebuilt. A probing caller learns nothing
        # about which write ids exist.
        store, write_id = _store()

        assert store.claim("no-such-id", lambda _pending: True) is None
        assert store.claim(write_id, lambda _pending: False) is None

    def test_the_predicate_is_not_called_for_an_unknown_id(self):
        # Otherwise a predicate that raises on a missing write would
        # turn a routine 404 into a 500, and the shape of the error
        # would tell a prober the id was absent.
        store, _ = _store()
        called = []

        store.claim("no-such-id", lambda pending: called.append(pending) or True)

        assert called == []


class TestAwaiting:
    """Listing what a reviewer may decide on.

    WITHOUT IT, FOUR-EYES IS ENFORCEABLE AND UNREACHABLE. Confirming a
    write requires its id, and only the proposer had one -- so the
    single person who could find a write was the single person a
    four-eyes rule forbids from approving it.
    """

    def test_lists_a_write_the_caller_may_claim(self):
        store, write_id = _store()

        listed = store.awaiting(lambda _pending: True)

        assert [item[0] for item in listed] == [write_id]

    def test_hides_a_write_the_caller_may_not_claim(self):
        store, _ = _store()

        assert store.awaiting(lambda _pending: False) == []

    def test_listing_does_not_consume_anything(self):
        # An inbox is read constantly. If looking at it removed writes,
        # the first reviewer to open the page would destroy the queue.
        store, write_id = _store()

        store.awaiting(lambda _pending: True)

        assert store.claim(write_id, lambda _pending: True) is not None

    def test_what_is_listed_can_always_be_claimed(self):
        # THE PROPERTY THAT MAKES AN INBOX HONEST, and the reason both
        # take the same predicate. Deciding eligibility separately is
        # how a queue ends up showing rows that 404 -- or worse, hiding
        # a decision somebody is waiting on.
        store, _ = _store()
        eligible = lambda pending: pending.action_type_name == "RenameAuthor"  # noqa: E731

        listed = store.awaiting(eligible)

        for write_id, _pending in listed:
            assert store.claim(write_id, eligible) is not None

    def test_an_expired_write_is_not_listed(self):
        # A stale entry in an inbox is worse than an absent one: the
        # reviewer spends attention on a decision that has already been
        # taken away from them.
        from datetime import timedelta

        store = PendingWriteStore(ttl=timedelta(seconds=-1))
        store.store(_pending())

        assert store.awaiting(lambda _pending: True) == []

    def test_reports_when_a_write_expires(self):
        store, write_id = _store()

        assert store.expires_at(write_id) is not None
        assert store.expires_at("no-such-id") is None
