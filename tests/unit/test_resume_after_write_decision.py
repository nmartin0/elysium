"""A query survives a human deciding a write.

AL-12. A proposed write ENDS the run: the loop returns with
`pending_write` set and the caller takes the decision to a human.
Until now that was the end of the query -- whatever the question was
went unanswered, and the person had to ask again from scratch after
approving.

THE WRITE HALF NEEDED NOTHING, which is most of why this is small.
`confirm_and_execute()` already re-runs `check_access()` per sub_write
against the APPROVER, re-evaluates submission criteria with them
acting, and re-checks applicability against the current ontology. A
PendingWrite carries resolved object ids and mutations, so an approval
is bound to its arguments. That is the pattern the field converged on
-- argument binding, use-time revalidation, a stated residual window.

WHAT IS ADDED IS THE READ HALF, and it is one rule. Data gathered
BEFORE the pause was read under the grants the user held then. A human
decision takes minutes or hours. Continuing after their access was cut
would produce an answer assembled partly under one set of grants and
partly under another -- never authorised as a whole.

The loop already makes that exact objection WITHIN a run, re-resolving
the acting user every hop and stopping on a change. A pause is the
same hazard with a longer gap, so it gets the same answer rather than
a second rule that can drift from the first.
"""

import contextlib
import io

import pytest

from core.agent.agentic_loop import AgentLoopResult, StopReason
from core.deployment_loader import build_generation
from core.intermediate_layer.auth import UserRecord, resolve_user_record

USER_ID = "user_alice"

APPLIED = {"status": "applied", "rows_changed": 2}


class Scripted:
    max_concurrent_requests = 1

    def __init__(self, *steps):
        self._steps = list(steps)

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        return self._steps.pop(0) if self._steps else '{"step": "finish"}'


class FakePending:
    """Stands in for a PendingWrite.

    The write mediator's own path is covered by its own tests, and
    building a real proposal here would test propose_action() rather
    than resume(). What resume() needs from it is the action name.
    """

    action_type_name = "RecategorizeTransactions"


@pytest.fixture
def loop_and_user(synced_deployment):
    generation = build_generation(
        synced_deployment.config_dir,
        synced_deployment.data_dir,
        synced_deployment.log_dir,
    )
    user = resolve_user_record(
        generation.config.users, USER_ID, generation.config.security_attribute
    )
    assert user.role_name is not None, "the fixture user has no role"
    return generation.loop, user


def _paused(gathered=None, hops_used=3):
    return AgentLoopResult(
        gathered=list(gathered or []),
        pending_write=FakePending(),
        stop_reason=StopReason.PROPOSED_WRITE,
        hops_used=hops_used,
    )


def _resume(loop, user, previous, refresh_user=None, steps=('{"step": "finish"}',)):
    loop.client = Scripted(*steps)
    with contextlib.redirect_stdout(io.StringIO()):
        return loop.resume(previous, user, "what changed?", APPLIED,
                           refresh_user=refresh_user)


# ------------------------------------------------------------ the read rule


def test_authority_lost_while_waiting_stops_the_resume(loop_and_user):
    """THE RULE THIS ITEM EXISTS FOR.

    The account is gone or disabled by the time the human decides.
    What was already gathered is kept -- it WAS authorised when it was
    read, and discarding it would lose information the user was
    entitled to -- but nothing further is read or sent to a model.
    """
    loop, user = loop_and_user
    previous = _paused([{"step": "get_field", "object_type": "Customer",
                         "object_id": "cust_001", "field_name": "email",
                         "result": "ada.okafor@example.com"}])

    result = _resume(loop, user, previous, refresh_user=lambda: None)

    assert result.stop_reason == StopReason.AUTHORITY_CHANGED
    assert result.gathered == previous.gathered


def test_a_changed_role_stops_the_resume_too(loop_and_user):
    """Not only a deleted account: a role or region change is the same
    hazard. The loop compares the whole record, as it does per hop.

    THIS ONE IS ALSO CAUGHT BY THE PER-HOP BACKSTOP inside _run(), as
    a control showed -- removing the resume check entirely leaves it
    passing. It is kept because the property is worth stating, and
    the two tests below are the ones that distinguish the resume check
    from the backstop.
    """
    loop, user = loop_and_user
    demoted = UserRecord(user.user_id, user.security_value, "some_other_role")

    result = _resume(loop, user, _paused(), refresh_user=lambda: demoted)

    assert result.stop_reason == StopReason.AUTHORITY_CHANGED


def test_nothing_is_read_on_behalf_of_a_changed_user(loop_and_user):
    """CHECKED FIRST -- before the schema is built, before the outcome
    is appended, before the model is called.

    THIS IS WHAT DISTINGUISHES THE RESUME CHECK FROM THE BACKSTOP, and
    a control is why it is written this way. _run() already
    re-resolves the user at the top of every hop, so simply deleting
    the resume check still ends as AUTHORITY_CHANGED -- via the
    backstop, one read too late. By then visible_schema() has been
    computed on behalf of a user whose authority is gone.

    Asserting on the READ, not on the outcome, is the only way to tell
    the two apart.
    """
    loop, user = loop_and_user
    reads = []
    real_visible_schema = loop.mediator.visible_schema

    def counting(*args, **kwargs):
        reads.append(args)
        return real_visible_schema(*args, **kwargs)

    loop.mediator.visible_schema = counting
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = loop.resume(_paused(), user, "what changed?", APPLIED,
                                 refresh_user=lambda: None)
    finally:
        loop.mediator.visible_schema = real_visible_schema

    assert result.stop_reason == StopReason.AUTHORITY_CHANGED
    assert reads == [], "read on behalf of a user whose authority had changed"


def test_unchanged_authority_carries_on(loop_and_user):
    loop, user = loop_and_user

    result = _resume(loop, user, _paused(), refresh_user=lambda: user)

    assert result.stop_reason == StopReason.FINISHED


# ------------------------------------------------------ carrying the state


def test_the_write_decision_reaches_the_answer(loop_and_user):
    """UNDER "result", which is not cosmetic.

    filter_real_data() strips any entry whose result is None, so a
    flat entry would reach the PLANNER and be invisible to SYNTHESIS
    -- the model would pick its next step knowing the write happened
    and then write an answer that never mentions it.
    """
    loop, user = loop_and_user

    result = _resume(loop, user, _paused(), refresh_user=lambda: user)

    decisions = [e for e in result.gathered if e["step"] == "write_decision"]
    assert len(decisions) == 1
    assert decisions[0]["result"] == APPLIED
    assert decisions[0]["action_type"] == "RecategorizeTransactions"
    # AND IT SURVIVES THE FILTER, which is the half that matters.
    assert any(e["step"] == "write_decision"
               for e in loop.filter_real_data(result.gathered))


def test_what_was_already_gathered_survives(loop_and_user):
    loop, user = loop_and_user
    before = [{"step": "get_field", "object_type": "Customer",
               "object_id": "cust_001", "field_name": "email",
               "result": "ada.okafor@example.com"}]

    result = _resume(loop, user, _paused(before), refresh_user=lambda: user)

    assert result.gathered[0] == before[0]


def test_the_hop_budget_continues_rather_than_restarting(loop_and_user):
    """An action that proposed a write every hop would otherwise get an
    unbounded total, one human approval at a time."""
    loop, user = loop_and_user
    loop.max_hops = 4

    result = _resume(loop, user, _paused(hops_used=3), refresh_user=lambda: user,
                     steps=('{"step": "get_field", "object_type": "Customer", '
                            '"object_id": "cust_001", "field_name": "email"}',
                            '{"step": "get_field", "object_type": "Customer", '
                            '"object_id": "cust_002", "field_name": "email"}'))

    # One hop left of four, so it runs out rather than taking two.
    assert result.hops_used == 4
    assert result.stop_reason == StopReason.MAX_HOPS


def test_the_duplicate_guard_still_sees_what_came_before(loop_and_user):
    """Resuming must not hand the model a clean slate to repeat itself
    on. The signatures are rebuilt from the prior gathered."""
    loop, user = loop_and_user
    step = ('{"step": "get_field", "object_type": "Customer", '
            '"object_id": "cust_001", "field_name": "email"}')
    first = _resume(loop, user, _paused(), refresh_user=lambda: user,
                    steps=(step, '{"step": "finish"}'))

    # ONE repeat, not three -- and a control is why. With three, the
    # guard fires either way: blind to the prior signatures the model
    # simply repeats itself twice more within the resumed run and trips
    # the cap anyway. Only the FIRST repeat distinguishes a guard that
    # remembers from one that does not.
    again = _resume(loop, user, _paused(first.gathered), refresh_user=lambda: user,
                    steps=(step, '{"step": "finish"}'))

    assert any(e["step"] == "rejected_duplicate" for e in again.gathered), (
        "the first repeat after a resume was treated as a new step"
    )


# ---------------------------------------------------------------- fail closed


def test_resuming_a_run_that_proposed_nothing_is_refused(loop_and_user):
    """Silently granting a second hop budget to a run that simply
    finished, and telling the model about a write that never happened,
    are both worse than an error."""
    loop, user = loop_and_user
    finished = AgentLoopResult(gathered=[], stop_reason=StopReason.FINISHED)

    with pytest.raises(ValueError, match="proposed a write"):
        loop.resume(finished, user, "what changed?", APPLIED)
