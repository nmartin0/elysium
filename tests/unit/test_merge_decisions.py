"""
Proposed merges, what was decided, and what a decision changes
(GOLD-6, closing the loop).

"AN APPROVED INFERENCE BECOMES STORED DATA, NOT EDITED CONFIG",
because "if approving a merge rewrote ontology_schema.yaml, then
configuration -- the thing a human wrote and reviews -- would silently
grow entries nobody typed" (FUSION_AND_IDENTITY.md).

AND THE POINT OF THIS FILE: there is no code path from a candidate to
a merge that does not pass through a person. "Inference never decides"
stops being a promise here and becomes a property of the code.
"""

import pytest

from core.identity_decisions import APPROVED, PENDING, REJECTED, MergeDecisionStore
from core.mirror.identity import resolve

TYPE = {
    "id_field": "customer_id",
    "security": {"field": "region"},
    "storage": {"silo": "b", "table": "customers", "id_column": "cust_pk"},
    "additional_storage": {"crm": {"silo": "c", "table": "contacts",
                                    "id_column": "contact_id"}},
    "identity": {"match_on": ["email"]},
    "fields": {
        "customer_id": {"type": "data", "column": "cust_pk"},
        "region": {"type": "data"},
        "email": {"type": "data"},
        "name": {"type": "data"},
    },
}
# The rule matches nothing here: different emails, so only a decision
# can join them.
ROWS = {
    None: [{"cust_pk": "c1", "email": "ada@billing", "region": "us-west", "name": "Ada"},
           {"cust_pk": "c2", "email": "ben@billing", "region": "us-west", "name": "Ben"}],
    "crm": [{"contact_id": "9f2a", "email": "ada@crm", "region": "us-west",
             "name": "Ada Okafor"}],
}


@pytest.fixture
def store(tmp_path):
    return MergeDecisionStore(tmp_path / "decisions.db")


class TestTheStore:
    def test_a_proposal_starts_pending(self, store):
        store.propose("Customer", "primary:c1", "crm:9f2a", 0.89)

        proposal = store.proposals("Customer")[0]
        assert proposal.decision == PENDING and proposal.decided_by is None

    def test_the_same_pair_proposed_twice_is_one_proposal(self, store):
        """Ordered before storing, so a reviewer does not decide the
        same merge twice and have the second look like disagreement."""
        first = store.propose("Customer", "primary:c1", "crm:9f2a", 0.89)
        second = store.propose("Customer", "crm:9f2a", "primary:c1", 0.91)

        assert first == second and len(store.proposals("Customer")) == 1

    def test_a_decision_records_who_made_it(self, store):
        proposal_id = store.propose("Customer", "primary:c1", "crm:9f2a", 0.89)

        store.decide(proposal_id, APPROVED, "alice", note="same person, checked")

        proposal = store.proposals("Customer")[0]
        assert proposal.decision == APPROVED and proposal.decided_by == "alice"

    def test_changing_your_mind_is_a_NEW_decision(self, store):
        """Append-only: what makes "why is this merged?" answerable a
        year later."""
        proposal_id = store.propose("Customer", "primary:c1", "crm:9f2a", 0.89)
        store.decide(proposal_id, APPROVED, "alice")

        store.decide(proposal_id, REJECTED, "bob", note="different people")

        assert store.proposals("Customer")[0].decision == REJECTED
        assert store.approved_pairs("Customer") == []

    def test_an_unknown_proposal_cannot_be_decided(self, store):
        with pytest.raises(ValueError, match="no such proposal"):
            store.decide("nope", APPROVED, "alice")

    def test_only_approve_or_reject(self, store):
        proposal_id = store.propose("Customer", "primary:c1", "crm:9f2a", 0.89)

        with pytest.raises(ValueError, match="must be"):
            store.decide(proposal_id, "maybe", "alice")

    def test_proposals_are_listed_per_object_type(self, store):
        store.propose("Customer", "primary:c1", "crm:9f2a", 0.89)
        store.propose("Supplier", "primary:s1", "crm:s2", 0.99)

        assert len(store.proposals("Customer")) == 1
        assert len(store.proposals("Supplier")) == 1


class TestNothingMergesWithoutAPerson:
    def test_a_pending_proposal_merges_NOTHING(self, store):
        """The property the whole design rests on."""
        store.propose("Customer", "primary:c1", "crm:9f2a", 0.99)

        resolution = resolve(TYPE, ROWS, approved_pairs=store.approved_pairs("Customer"))

        assert resolution.merged_count == 0
        assert sorted(resolution.entities) == ["c1", "c2", "crm:9f2a"]

    def test_a_rejected_proposal_merges_nothing_either(self, store):
        proposal_id = store.propose("Customer", "primary:c1", "crm:9f2a", 0.99)
        store.decide(proposal_id, REJECTED, "alice")

        resolution = resolve(TYPE, ROWS, approved_pairs=store.approved_pairs("Customer"))

        assert resolution.merged_count == 0

    def test_an_APPROVED_proposal_merges(self, store):
        proposal_id = store.propose("Customer", "primary:c1", "crm:9f2a", 0.99)
        store.decide(proposal_id, APPROVED, "alice")

        resolution = resolve(TYPE, ROWS, approved_pairs=store.approved_pairs("Customer"))

        assert resolution.merged_count == 1
        assert sorted(str(key) for key in resolution.entities["c1"]) == ["None", "crm"]

    def test_and_the_others_are_left_alone(self, store):
        proposal_id = store.propose("Customer", "primary:c1", "crm:9f2a", 0.99)
        store.decide(proposal_id, APPROVED, "alice")

        resolution = resolve(TYPE, ROWS, approved_pairs=store.approved_pairs("Customer"))

        assert list(resolution.entities["c2"]) == [None]


class TestWhatAnApprovalCannotDo:
    def test_it_cannot_overrule_D2(self, store):
        """An approval cannot make two security values agree. Merging
        would silently decide who can see the result, which is the one
        thing identity resolution declines to do."""
        rows = {
            None: [{"cust_pk": "c1", "email": "ada@billing", "region": "us-west"}],
            "crm": [{"contact_id": "9f2a", "email": "ada@crm", "region": "eu"}],
        }
        proposal_id = store.propose("Customer", "primary:c1", "crm:9f2a", 0.99)
        store.decide(proposal_id, APPROVED, "alice")

        resolution = resolve(TYPE, rows, approved_pairs=store.approved_pairs("Customer"))

        assert resolution.merged_count == 0
        assert sorted(resolution.entities) == ["c1", "crm:9f2a"]
        assert resolution.refused

    def test_an_approval_for_rows_that_do_not_exist_changes_nothing(self, store):
        proposal_id = store.propose("Customer", "primary:gone", "crm:also-gone", 0.99)
        store.decide(proposal_id, APPROVED, "alice")

        resolution = resolve(TYPE, ROWS, approved_pairs=store.approved_pairs("Customer"))

        assert sorted(resolution.entities) == ["c1", "c2", "crm:9f2a"]


class TestChains:
    def test_a_to_b_and_b_to_c_is_one_entity(self, store):
        """Three records of one person, approved pairwise."""
        rows = {
            None: [{"cust_pk": "c1", "email": "one@x", "region": "us-west"},
                   {"cust_pk": "c9", "email": "two@x", "region": "us-west"}],
            "crm": [{"contact_id": "9f2a", "email": "three@x", "region": "us-west"}],
        }
        for left, right in (("primary:c1", "primary:c9"), ("primary:c9", "crm:9f2a")):
            store.decide(store.propose("Customer", left, right, 0.99), APPROVED, "alice")

        resolution = resolve(TYPE, rows, approved_pairs=store.approved_pairs("Customer"))

        assert len(resolution.entities) == 1
        assert len(next(iter(resolution.entities.values()))) == 2  # two storages
