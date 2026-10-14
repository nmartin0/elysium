"""R58: what approving a proposal would make one entity.

core/mirror/identity._union takes the transitive closure of approved
pairs at build time; group_if_approved computes the same closure at
decision time, so a reviewer can be shown it first.
"""

from core.identity_decisions import APPROVED, REJECTED, MergeDecisionStore


def _store(tmp_path):
    return MergeDecisionStore(tmp_path / "identity_decisions.db")


def _proposal(store, proposal_id):
    return next(p for p in store.proposals() if p.proposal_id == proposal_id)


def test_a_lone_pair_joins_only_itself(tmp_path):
    store = _store(tmp_path)
    ab = store.propose("Customer", "a", "b", 0.9)

    assert store.group_if_approved(_proposal(store, ab)) == ["a", "b"]


def test_an_approved_neighbour_is_pulled_in(tmp_path):
    store = _store(tmp_path)
    store.decide(store.propose("Customer", "b", "c", 0.9), APPROVED, "x")
    ab = store.propose("Customer", "a", "b", 0.9)

    assert store.group_if_approved(_proposal(store, ab)) == ["a", "b", "c"]


def test_it_bridges_two_groups(tmp_path):
    store = _store(tmp_path)
    store.decide(store.propose("Customer", "a", "x", 0.9), APPROVED, "r")
    store.decide(store.propose("Customer", "b", "y", 0.9), APPROVED, "r")
    ab = store.propose("Customer", "a", "b", 0.9)

    assert store.group_if_approved(_proposal(store, ab)) == ["a", "b", "x", "y"]


def test_a_rejected_or_pending_neighbour_is_not(tmp_path):
    """THE CONTROL: only approvals chain."""
    store = _store(tmp_path)
    store.decide(store.propose("Customer", "b", "c", 0.9), REJECTED, "x")
    store.propose("Customer", "b", "d", 0.9)
    ab = store.propose("Customer", "a", "b", 0.9)

    assert store.group_if_approved(_proposal(store, ab)) == ["a", "b"]


def test_another_types_approvals_do_not_chain(tmp_path):
    store = _store(tmp_path)
    store.decide(store.propose("Supplier", "b", "c", 0.9), APPROVED, "x")
    ab = store.propose("Customer", "a", "b", 0.9)

    assert store.group_if_approved(_proposal(store, ab)) == ["a", "b"]
