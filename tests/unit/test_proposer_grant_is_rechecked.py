"""A proposer's execute grant is re-checked when the rules change
(SEC-14).

THE INVARIANT THIS WAS MISSING. `SECURITY_ARCHITECTURE.md`:

    AUTHORITY IS NEVER STORED. It is re-evaluated at the point of use,
    against the CURRENT generation. A pending write survives a restart
    and a reload, so a decision taken at proposal would be taken under
    rules that may no longer exist.

Confirm already re-evaluated a good deal -- submission criteria
against the approver, constraints, fields the ontology no longer
declares, and MAC against the approver. It did NOT re-evaluate the
PROPOSER's own `execute:` grant, so an action whose grant was revoked
from a role after proposal could still be approved and run.

NOT THEORETICAL. Runtime role editing exists: `manage:roles` is a real
grant, `core/role_changes.py` applies changes to a live deployment,
and the pending queue's TTL is fifteen minutes. Revoking a grant from
a role is exactly the remedy an operator reaches for, and it did not
reach the queue.

ONLY WHEN THE GENERATION CHANGED, and that is not an optimisation. A
first version checked on every confirm and broke 23 tests that build a
PendingWrite directly without going through propose_action -- it was
refusing writes whose proposer had lost nothing. A guard that fires
when nothing has changed is not enforcing an invariant, it is just
failing. If the generation is the same, the roles are the same object
and the question was already answered at proposal.

WHAT IT DOES NOT CATCH, tested below so the gap is visible rather than
implied: `pending.proposer` is a snapshot, so a proposer who has since
been DISABLED, DELETED or MOVED TO ANOTHER ROLE is not detected here.
That needs the user directory, which this mediator does not hold.
Filed in REQUESTS_security.md.
"""

from datetime import UTC, datetime

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite, WriteMediator

GRANTED = {"agent": {"allowed_actions": ["execute:MoveCustomer"]}}
REVOKED = {"agent": {"allowed_actions": []}}
MOVED = {"agent": {"allowed_actions": ["execute:SomethingElse"]}}


def _mediator(roles: dict, generation: int) -> WriteMediator:
    mediator = object.__new__(WriteMediator)
    mediator.roles = roles
    mediator.generation = generation
    return mediator


def _pending(proposed_under: int, role_name: str = "agent") -> PendingWrite:
    return PendingWrite(
        sub_writes=(SubWrite("Customer", "c1", "update", {"name": "Ada"}, {"name": "Old"}),),
        user_id="alice",
        description="move c1",
        action_type_name="MoveCustomer",
        origin="api",
        proposed_at=datetime.now(UTC),
        proposed_under_generation=proposed_under,
        parameters={},
        proposer=UserRecord(user_id="alice", security_value="us-west", role_name=role_name),
    )


def _check(mediator, pending):
    mediator._refuse_if_the_proposer_lost_the_grant(pending)


class TestARevokedGrantStopsTheWrite:
    def test_the_grant_was_taken_away_after_proposal(self):
        """THE DEFECT. Proposed under generation 1, confirmed under 2,
        and the role no longer grants the action."""
        with pytest.raises(ValueError, match="no longer holds"):
            _check(_mediator(REVOKED, generation=2), _pending(proposed_under=1))

    def test_the_grant_was_replaced_with_a_different_one(self):
        with pytest.raises(ValueError, match="no longer holds"):
            _check(_mediator(MOVED, generation=2), _pending(proposed_under=1))

    def test_the_refusal_names_both_generations_and_what_to_do(self):
        """A refusal nobody can act on becomes a support ticket."""
        with pytest.raises(ValueError) as raised:
            _check(_mediator(REVOKED, generation=7), _pending(proposed_under=3))

        message = str(raised.value)
        assert "'alice'" in message
        assert "'execute:MoveCustomer'" in message
        assert "7" in message and "3" in message
        assert "Re-propose" in message

    def test_a_role_that_no_longer_exists_at_all(self):
        with pytest.raises(ValueError, match="no longer holds"):
            _check(_mediator({}, generation=2), _pending(proposed_under=1))


class TestWhatMustStillGetThrough:
    """THE OPPOSITE DIRECTION, and it is nearly all of the traffic."""

    def test_an_unchanged_generation_is_not_re_examined(self):
        """Not an optimisation -- the question was answered at
        proposal against these very roles. A first version without
        this broke 23 tests by refusing writes that had lost
        nothing."""
        _check(_mediator(REVOKED, generation=1), _pending(proposed_under=1))

    def test_a_reload_that_kept_the_grant(self):
        """A configuration reload is ordinary; most change nothing
        about this role."""
        _check(_mediator(GRANTED, generation=2), _pending(proposed_under=1))

    def test_a_grant_added_since_proposal_is_fine(self):
        roles = {"agent": {"allowed_actions": ["execute:MoveCustomer", "execute:Extra"]}}

        _check(_mediator(roles, generation=2), _pending(proposed_under=1))


def test_a_disabled_proposer_is_NOT_caught_here():
    """THE KNOWN GAP, pinned so it is visible rather than implied.

    `pending.proposer` is a snapshot taken at proposal. A proposer
    disabled or deleted since still carries a role_name that grants the
    action, so this check passes them. Catching that needs the user
    directory, which this mediator does not hold and which is wired in
    api/routes.py.

    If a later change threads the directory through, this test should
    FAIL and be replaced -- that is the point of writing it down.
    """
    _check(_mediator(GRANTED, generation=2), _pending(proposed_under=1))
