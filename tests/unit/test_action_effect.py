"""
A condition proposing a write, rather than a notice.

AS THE OWNER, which is Foundry's split and the one
TRIGGERS_AND_PLUGINS.md already states: "action effects execute AS the
owner. Submission criteria are evaluated against the owner; the audit
log records the owner."

A notification is evaluated per RECIPIENT; an action is not, because
an action is a write and a write has one author.

RE-RUN RATHER THAN REMEMBERED, and that resolves a tension this design
created. Conditions compare COUNTS -- no alerting system worth copying
stores last time's result set -- so when one fires, nothing knows
WHICH objects matched.

So the effect asks again. The set may differ slightly from the one
that tripped the count, and that is the RIGHT answer rather than a
compromise: an action should operate on what matches when it RUNS,
not on what matched when somebody noticed.

IT PROPOSES, IT DOES NOT EXECUTE. The pending write lands in the
approvals queue like any other, with origin="automation" so whoever
reviews it can tell a condition proposed it.
"""

import pytest

from core.count_condition import propose_action_effect
from core.intermediate_layer.auth import UserRecord
from core.saved_views import SavedView


@pytest.fixture
def generation():
    from core.deployment_loader import build_generation, resolve_runtime_paths

    paths = resolve_runtime_paths()
    return build_generation(paths.config_dir, paths.data_dir, paths.log_dir)


@pytest.fixture
def owner():
    return UserRecord("debug", "us-west", "debug")


def _view(conditions=None):
    return SavedView(
        "v1", "All transactions", "Transaction", "",
        conditions or [], "2026-01-01T00:00:00+00:00",
    )


def _propose(generation, owner, view=None):
    return propose_action_effect(
        generation.write_mediator, generation.mediator,
        view or _view(), owner,
        "RecategorizeTransactions", "transaction_ids",
        {"new_category": "reviewed"},
    )


class TestItProposesARealWrite:
    def test_a_pending_write_comes_back(self, generation, owner):
        assert _propose(generation, owner) is not None

    def test_it_covers_every_matching_object(self, generation, owner):
        pending = _propose(generation, owner)

        assert len(pending.sub_writes) == len(
            generation.mediator.search_object(owner, "Transaction", []),
        )

    def test_the_origin_says_a_condition_proposed_it(self, generation, owner):
        """origin REACHES THE AUDIT TRAIL AND THE APPROVAL CRITERIA, so
        whoever reviews the queue can tell this from something a
        colleague proposed."""
        assert _propose(generation, owner).origin == "automation"

    def test_it_is_proposed_by_the_owner(self, generation, owner):
        assert _propose(generation, owner).user_id == owner.user_id


class TestAnEmptySetProposesNothing:
    def test_nothing_comes_back(self, generation, owner):
        """AN ACTION OVER AN EMPTY SET is a decision somebody has to
        read and dismiss."""
        matches_nothing = _view(conditions=[
            {"field": "amount", "operator": "equals", "value": "-1.00"},
        ])

        assert _propose(generation, owner, matches_nothing) is None


class TestItUsesTheOwnersAuthority:
    def test_a_narrower_owner_proposes_a_narrower_write(self, generation):
        """THE WRITE COVERS WHAT THE OWNER CAN SEE, not what anybody
        can. A condition owned by somebody with one partition must not
        act on another's."""
        west = _propose(generation, UserRecord("w", "us-west", "debug"))
        east = _propose(generation, UserRecord("e", "us-east", "debug"))

        assert len(west.sub_writes) != len(east.sub_writes)


class TestItDoesNotExecute:
    def test_the_write_is_pending_rather_than_applied(self, generation, owner):
        """A PROPOSAL, NOT A WRITE. The approvals queue decides, and
        the previous commit's `automatable: false` decides whether a
        condition may even get this far."""
        before = generation.mediator.get_field(
            owner, "Transaction", "1", "category",
        )

        _propose(generation, owner)

        assert generation.mediator.get_field(
            owner, "Transaction", "1", "category",
        ) == before
