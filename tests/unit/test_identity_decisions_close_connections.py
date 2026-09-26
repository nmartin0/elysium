"""The merge decision store closes what it opens (SEC-15).

FOUND READING core/identity_decisions.py, not from any audit row.

The store opened a bare `sqlite3.connect()` and used it as
`with self._connection() as conn:`. That commits on a clean exit and
does NOT close -- documented Python behaviour, and a trap precisely
because the `with` makes it look handled. MEASURED before fixing:

    100 calls to propose()/decide() -> 54 file descriptors left open

NOT DORMANT CODE. `scripts/run_sync.py:384` builds this store on every
sync, and `scripts/backup_deployment.py` backs its database up. A
large identity run decides per candidate pair, so this ends in
"Too many open files" and takes the sync with it.

THE FIX IS TO USE THE PROJECT'S OWN HELPER rather than to add a
close(). `connection_with_schema()` closes in a `finally` and brings
WAL, the per-connection query deadline and once-per-process schema
verification -- none of which this store had while it opened its own
connections. That it was the only store not using it is the tell.

AND THE FIX COULD HAVE SILENTLY BROKEN PERSISTENCE. The helper does
NOT auto-commit, where the bare connection did. Every writer now
commits explicitly, and the reopen test below is what proves it --
without that, this would have "fixed" the leak by writing nothing.
"""

import os
from pathlib import Path

import pytest

from core.identity_decisions import APPROVED, PENDING, REJECTED, MergeDecisionStore


def _open_fds() -> int:
    return len(os.listdir("/proc/self/fd"))


@pytest.fixture
def database(tmp_path) -> Path:
    return tmp_path / "identity_decisions.db"


class TestItClosesWhatItOpens:
    def test_a_hundred_calls_leak_no_descriptors(self, database):
        store = MergeDecisionStore(database)
        before = _open_fds()

        proposals = [store.propose("Customer", f"a{i}", f"b{i}", 0.9) for i in range(50)]
        for proposal_id in proposals:
            store.decide(proposal_id, APPROVED, "alice")

        assert _open_fds() == before

    def test_reads_leak_nothing_either(self, database):
        store = MergeDecisionStore(database)
        store.propose("Customer", "a", "b", 0.9)
        before = _open_fds()

        for _ in range(50):
            store.proposals("Customer")
            store.approved_pairs("Customer")

        assert _open_fds() == before


class TestItStillPersists:
    """THE HALF THE FIX COULD HAVE BROKEN. The helper does not
    auto-commit; a leak-free store that writes nothing is worse than
    the leak."""

    def test_a_proposal_survives_reopening_the_database(self, database):
        proposal_id = MergeDecisionStore(database).propose("Customer", "a", "b", 0.91)

        reopened = MergeDecisionStore(database).proposals("Customer")

        assert [p.proposal_id for p in reopened] == [proposal_id]
        assert reopened[0].decision == PENDING

    def test_a_decision_survives_reopening(self, database):
        store = MergeDecisionStore(database)
        proposal_id = store.propose("Customer", "a", "b", 0.91)
        store.decide(proposal_id, APPROVED, "alice", note="same person")

        reopened = MergeDecisionStore(database).proposals("Customer")

        assert reopened[0].decision == APPROVED
        assert reopened[0].decided_by == "alice"

    def test_approved_pairs_survive(self, database):
        store = MergeDecisionStore(database)
        store.decide(store.propose("Customer", "a", "b", 0.9), APPROVED, "alice")

        assert MergeDecisionStore(database).approved_pairs("Customer") == [("a", "b")]


class TestTheBehaviourItAlreadyPromised:
    """Unchanged by this fix, and pinned while the connection handling
    moved underneath it."""

    def test_inference_never_decides(self, database):
        """A proposal nobody decided merges nothing -- the property the
        module docstring calls a property of the code."""
        store = MergeDecisionStore(database)
        store.propose("Customer", "a", "b", 0.99)

        assert store.approved_pairs("Customer") == []

    def test_a_change_of_mind_appends_and_the_latest_wins(self, database):
        store = MergeDecisionStore(database)
        proposal_id = store.propose("Customer", "a", "b", 0.9)
        store.decide(proposal_id, APPROVED, "alice")
        store.decide(proposal_id, REJECTED, "bob", note="different people")

        assert MergeDecisionStore(database).approved_pairs("Customer") == []
        assert store.proposals("Customer")[0].decided_by == "bob"

    def test_the_same_pair_from_either_direction_is_one_proposal(self, database):
        store = MergeDecisionStore(database)

        first = store.propose("Customer", "a", "b", 0.9)
        second = store.propose("Customer", "b", "a", 0.9)

        assert first == second

    def test_a_decision_on_a_missing_proposal_is_refused(self, database):
        with pytest.raises(ValueError, match="no such proposal"):
            MergeDecisionStore(database).decide("nope", APPROVED, "alice")

    def test_an_invalid_decision_word_is_refused(self, database):
        store = MergeDecisionStore(database)
        proposal_id = store.propose("Customer", "a", "b", 0.9)

        with pytest.raises(ValueError):
            store.decide(proposal_id, "maybe", "alice")
