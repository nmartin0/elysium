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


class TestTheTTLIsConfigurable:
    """How long a reviewer has to decide.

    FIFTEEN MINUTES WAS THE HARDCODED DEFAULT, which was right when the
    proposer confirmed their own write seconds later and wrong for an
    approvals queue: the point of four-eyes is that the reviewer is
    somebody else, and somebody else is not necessarily at their desk.
    """

    def test_the_store_honours_the_ttl_it_is_given(self):
        from datetime import timedelta

        store = PendingWriteStore(ttl=timedelta(seconds=-1))
        write_id = store.store(_pending())

        assert store.claim(write_id, lambda _pending: True) is None

    def test_a_longer_ttl_keeps_a_write_decidable(self):
        # THE CONTROL. A store that expired everything would pass the
        # test above while making the feature useless.
        from datetime import timedelta

        store = PendingWriteStore(ttl=timedelta(hours=4))
        write_id = store.store(_pending())

        assert store.claim(write_id, lambda _pending: True) is not None

    def test_the_deployment_default_is_long_enough_to_be_useful(self):
        # A four-hour default is long enough for a reviewer to be in a
        # meeting and short enough that a forgotten proposal does not
        # outlive the context that produced it. Asserted against the
        # real config rather than the constant, because the constant is
        # only a fallback now.
        from pathlib import Path

        from core.deployment_loader import load_deployment

        config = load_deployment(
            Path(__file__).resolve().parent.parent.parent / "deployment" / "etc",
        )

        assert config.pending_write_ttl_minutes >= 60


class TestBothCategories:
    """An inbox shows what you may decide AND what you proposed.

    Following Foundry, whose Approvals inbox filters "Your inbox" and
    "Created by you" rather than showing only one.

    THE PROPOSER NEEDS THE SECOND ESPECIALLY ONCE FOUR-EYES IS ON: they
    cannot approve their own write, so without this they propose
    something and have no way to see whether anyone has looked at it. A
    proposal that vanishes into silence is one people stop making.
    """

    def test_a_proposer_sees_their_own_write_even_without_the_grant(self):
        store, _ = _store()  # proposed by alice

        listed = store.awaiting(lambda pending: pending.user_id == "alice")

        assert len(listed) == 1

    def test_a_reviewer_sees_a_write_they_did_not_propose(self):
        store = PendingWriteStore()
        store.store(_pending(user_id="bob"))

        listed = store.awaiting(lambda _pending: True)

        assert [pending.user_id for _id, pending in listed] == ["bob"]

    def test_someone_with_neither_relationship_sees_nothing(self):
        # THE CONTROL. A predicate that returned everything would make
        # the inbox a directory of every write in the deployment.
        store = PendingWriteStore()
        store.store(_pending(user_id="bob"))

        assert store.awaiting(lambda pending: pending.user_id == "carol") == []
