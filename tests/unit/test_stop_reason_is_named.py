"""Every way the loop can stop names itself, and only a real finish
reads as complete.

LB-3 AND AL-6 ARE ONE DEFECT. AL-6 said "four booleans instead of one
stop reason"; LB-3 said "three code-detected failures presented as
complete answers". They are the same hole from two ends: four of the
ways `_run()` can end set no boolean at all, so the result was
byte-identical to a deliberate finish.

MEASURED BEFORE THE FIX, by driving the real loop into each:

    deliberate finish   cancelled=False hit_max_hops=False
                        authority_changed=False ran_out_of_time=False
    DUPLICATE spiral    identical
    UNKNOWN step kind   identical

THE UNKNOWN-STEP CASE WAS THE WORST. It stops on hop one having
gathered nothing, so `synthesize_insight()` is handed zero records and
returns "no matching records were found (either none exist, or they're
outside your access scope)" -- blaming the customer's data or the
caller's own permissions for what was a model failure. A wrong answer
delivered confidently is worse than an error.

REAL MEDIATOR, NOT A MOCK, deliberately. 001AGENTLOOP records that the
decimal crash (PA001-X2) reached the shipped configuration precisely
because the agent tests mock the mediator and hand back floats and
strings: the bug lived in the gap between a mocked mediator and a real
one. A spiral is a property of the loop driving real reads, so these
drive real reads.

WHAT THIS DOES NOT COVER, said plainly: `cancelled` and
`authority_changed` are exercised by their own existing tests, and
`ran_out_of_time` needs a deadline this file does not set up. They
were never part of the silence -- they always set a flag -- so the
cases added here are the four that did not.
"""

import contextlib
import io

import pytest

from core.agent.agentic_loop import StopReason
from core.deployment_loader import build_generation
from core.intermediate_layer.auth import resolve_user_record

# The shipped deployment names her user_alice. Passing "alice" returns
# an EMPTY UserRecord -- no role, no region -- and every read is then
# denied while the loop runs on happily, which is exactly how an
# earlier measurement of mine came out looking healthy and meaning
# nothing.
USER_ID = "user_alice"

A_REAL_SEARCH = (
    '{"step": "search_object", "object_type": "Customer", '
    '"filter": {"region": "us-west"}}'
)


class AlwaysSays:
    """A model with one thing to say, which is what a spiral IS."""

    max_concurrent_requests = 1

    def __init__(self, reply: str):
        self.reply = reply

    def chat(self, system_prompt, user_message, json_mode=False,
             temperature=None, *, deadline=None, usage=None):
        return self.reply


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
    # The fixture is worthless if this user cannot read -- every stop
    # below would then be reached for the wrong reason.
    assert user.role_name is not None, "the fixture user has no role"
    assert generation.mediator.visible_schema(user), "the fixture user sees no schema"
    return generation.loop, user


def _run(loop, user, reply):
    loop.client = AlwaysSays(reply)
    with contextlib.redirect_stdout(io.StringIO()):
        return loop.run(user, "Who are the customers?")


def test_a_deliberate_finish_is_the_only_complete_ending(loop_and_user):
    loop, user = loop_and_user
    result = _run(loop, user, '{"step": "finish"}')

    assert result.stop_reason == StopReason.FINISHED
    assert result.possibly_incomplete is False


def test_a_duplicate_spiral_does_not_read_as_a_finish(loop_and_user):
    """The model repeating one step until the guard stops it."""
    loop, user = loop_and_user
    result = _run(loop, user, A_REAL_SEARCH)

    assert result.stop_reason == StopReason.REPEATED_ITSELF
    assert result.possibly_incomplete is True
    # It really did read something, so this is a spiral rather than a
    # loop that never started.
    assert result.gathered


def test_an_unrecognised_step_does_not_read_as_a_finish(loop_and_user):
    """The case that produced a confidently wrong answer.

    Nothing is gathered, so before this change synthesis was told the
    search simply found nothing -- and said so, in words that blame the
    data or the caller's own access.
    """
    loop, user = loop_and_user
    result = _run(loop, user, '{"step": "teleport_object"}')

    # The reason comes from next_step(), which fails closed by
    # FABRICATING a finish -- so this is the string it stamps, not a
    # StopReason the loop chose. That is the point: the fabrication is
    # now visible instead of arriving as a legitimate finish.
    assert result.stop_reason == "unrecognised_step"
    assert result.possibly_incomplete is True
    assert result.gathered == []


def test_an_invalid_step_spiral_does_not_read_as_a_finish(loop_and_user):
    """Well-formed JSON, valid step name, unusable values."""
    loop, user = loop_and_user
    result = _run(
        loop, user,
        '{"step": "get_field", "object_type": "Customer", '
        '"object_id": {"not": "an id"}, "field_name": "name"}',
    )

    assert result.stop_reason in ("malformed_step", StopReason.INVALID_STEPS)
    assert result.possibly_incomplete is True


def test_max_hops_still_names_itself(loop_and_user):
    """The one ending that always DID set a flag, kept as the control
    for the others: if this broke while the rest passed, the reason
    field would be replacing a working signal rather than adding to it.
    """
    loop, user = loop_and_user
    loop.max_hops = 3
    # Distinct steps, so neither the duplicate guard nor the invalid
    # guard fires first -- the loop must run out of hops instead.
    replies = iter([
        '{"step": "search_object", "object_type": "Customer", "filter": {"region": "us-west"}}',
        '{"step": "get_field", "object_type": "Customer", "object_id": "cust_001", "field_name": "name"}',
        '{"step": "get_field", "object_type": "Customer", "object_id": "cust_001", "field_name": "email"}',
    ])

    class Sequence:
        max_concurrent_requests = 1

        def chat(self, *a, **k):
            return next(replies)

    loop.client = Sequence()
    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, "Who are the customers?")

    assert result.stop_reason == StopReason.MAX_HOPS
    assert result.hit_max_hops is True
    assert result.possibly_incomplete is True


def test_the_legacy_booleans_still_answer_for_their_own_reason():
    """27 call sites read these, including api/routes.py, which this
    branch does not own. They are derived from stop_reason now rather
    than stored beside it -- one fact, one place -- and this pins that
    the derivation is right in both directions.
    """
    from core.agent.agentic_loop import AgentLoopResult

    for reason, flag in (
        (StopReason.CANCELLED, "cancelled"),
        (StopReason.MAX_HOPS, "hit_max_hops"),
        (StopReason.AUTHORITY_CHANGED, "authority_changed"),
        (StopReason.RAN_OUT_OF_TIME, "ran_out_of_time"),
    ):
        result = AgentLoopResult(gathered=[], stop_reason=reason)
        assert getattr(result, flag) is True, f"{reason} should set {flag}"
        # And ONLY its own: a reason setting two flags would make the
        # derivation worse than the four fields it replaced.
        others = {"cancelled", "hit_max_hops", "authority_changed",
                  "ran_out_of_time"} - {flag}
        for other in others:
            assert getattr(result, other) is False, f"{reason} also set {other}"


def test_a_proposed_write_is_not_an_incomplete_answer():
    """A write proposal ends the run because a human must decide, not
    because anything was missed. Telling synthesis it may be partial
    would be wrong, and it is the case most easily swept into
    "everything that is not a finish is incomplete".
    """
    from core.agent.agentic_loop import AgentLoopResult

    result = AgentLoopResult(gathered=[{"a": 1}],
                             stop_reason=StopReason.PROPOSED_WRITE)
    assert result.possibly_incomplete is False


# ------------------------------------------- the rate, not just the last one


def test_every_unusable_reply_is_recorded_even_when_the_run_ends_well(loop_and_user):
    """THE GAP stop_reason CANNOT COVER.

    stop_reason names only the LAST ending, and only when it ended the
    run. A fabricated finish that gets nudged and is followed by a
    genuine finish leaves stop_reason saying FINISHED, and the fact
    that the model produced an unusable reply on the way survives
    nowhere but a log line. The RATE was not measurable from a result.

    WHY IT IS WORTH MEASURING: a published CPU tool-calling benchmark
    found that adding a fallback parser for non-standard output moved
    one model from 0.670 to 0.960 and moved another DOWN from 0.880 to
    0.780 -- a bigger swing than any model swap in its table. Our
    next_step() fails closed on every parse failure, so how often that
    fires matters more than which model is underneath it.

    DRIVEN THROUGH THE REAL LOOP, and a control is why. The first
    version constructed an AgentLoopResult directly, so it asserted
    the dataclass carried the field and never touched the code that
    fills it -- recording only on the path that STOPS the run passed
    it unchanged.

    THE ROUTE TO THE NUDGE took two attempts. _detect_asymmetry needs
    two objects OF THE SAME TYPE each with a get_field, whose field
    sets DIFFER -- a search result is a list and is ignored. So one
    customer gets one field read and the other gets two; then an
    unusable reply arrives, the asymmetry check nudges instead of
    stopping, and a genuine finish ends the run.
    """
    loop, user = loop_and_user
    replies = iter([
        '{"step": "get_field", "object_type": "Customer", "object_id": "cust_001", "field_name": "email"}',
        '{"step": "get_field", "object_type": "Customer", "object_id": "cust_002", "field_name": "email"}',
        '{"step": "get_field", "object_type": "Customer", "object_id": "cust_002", "field_name": "name"}',
        '{"step": "teleport_object"}',          # unusable -- fabricates a finish
        '{"step": "finish"}',                   # the genuine one
    ])

    class Sequence:
        max_concurrent_requests = 1

        def chat(self, *a, **k):
            return next(replies, '{"step": "finish"}')

    loop.client = Sequence()
    with contextlib.redirect_stdout(io.StringIO()):
        result = loop.run(user, "What are the customers' emails?")

    # Reads as a clean finish...
    assert result.stop_reason == StopReason.FINISHED
    assert result.possibly_incomplete is False
    # ...while still reporting the unusable reply it recovered from.
    assert result.fabricated_finishes == ("unrecognised_step",)


def test_a_run_with_no_parse_failures_records_none(loop_and_user):
    """The denominator has to be trustworthy too: a clean run must not
    report a failure it did not have."""
    loop, user = loop_and_user
    result = _run(loop, user, '{"step": "finish"}')

    assert result.fabricated_finishes == ()


def test_an_unusable_reply_that_ends_the_run_is_recorded_too(loop_and_user):
    """Recorded on BOTH paths -- the one that stops and the one that is
    nudged -- or the rate counts only half of them."""
    loop, user = loop_and_user
    result = _run(loop, user, '{"step": "teleport_object"}')

    assert result.fabricated_finishes == ("unrecognised_step",)
    assert result.stop_reason == "unrecognised_step"
