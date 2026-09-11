"""
The acting user is re-resolved every hop -- step 4a of
HOT_RELOAD_PLAN.md, and a security-backlog item that predates it.

Identity is resolved once when a request arrives. On CPU-only hardware
a query runs for minutes -- long enough for an administrator to disable
an account or change a role and reasonably expect it to take effect.
Before this, it took effect only after every hop had already run.

A CHANGE STOPS THE LOOP rather than continuing under the new authority.
Carrying on would produce an answer assembled partly under one set of
grants and partly under another, which was never authorized as a whole
-- the same objection as a torn read, and as an answer mixing two data
snapshots.
"""

from core.agent.agentic_loop import AgentLoop
from core.intermediate_layer.auth import UserRecord
from tests.conftest import scripted_llm_client

ALICE = UserRecord("alice", "us-west", "analyst")


class _Mediator:
    def __init__(self):
        self.reads = []

    def visible_schema(self, user_record):
        return {}

    def search_object(self, user_record, object_type, conditions, **kwargs):
        self.reads.append(object_type)
        return ["x1"]


def _loop(mediator, steps):
    loop = AgentLoop.__new__(AgentLoop)
    loop.client = scripted_llm_client(steps)
    loop.mediator = mediator
    loop.write_mediator = None
    loop.tools = []
    loop.max_hops = 6
    loop.max_consecutive_duplicates = 2
    loop.max_consecutive_invalid_steps = 2
    return loop


_SEARCH = {"step": "search_object", "object_type": "Customer", "filter": {}}


def test_an_unchanged_user_does_not_stop_the_loop():
    # The control. A refresher returning the same record must not
    # interrupt anything, or every query would stop on its second hop.
    mediator = _Mediator()
    loop = _loop(mediator, [_SEARCH, {"step": "finish"}])

    result = loop.run(ALICE, "q", refresh_user=lambda: ALICE)

    assert result.authority_changed is False
    assert mediator.reads, "the loop never ran a step"


def test_a_changed_role_stops_the_loop():
    mediator = _Mediator()
    loop = _loop(mediator, [_SEARCH, _SEARCH, {"step": "finish"}])
    records = [ALICE, UserRecord("alice", "us-west", "auditor")]

    result = loop.run(ALICE, "q", refresh_user=lambda: records.pop(0) if records else records)

    assert result.authority_changed is True


def test_a_disabled_account_stops_the_loop():
    # None means gone or disabled. The loop treats it the same as a
    # change: there is no authority to continue under.
    mediator = _Mediator()
    loop = _loop(mediator, [_SEARCH, _SEARCH, {"step": "finish"}])
    answers = [ALICE, None]

    result = loop.run(ALICE, "q", refresh_user=lambda: answers.pop(0))

    assert result.authority_changed is True


def test_work_already_done_is_returned_not_discarded():
    # It WAS authorized when it was read. Discarding it would lose
    # information the user was entitled to, and tell them less about
    # what happened on their behalf.
    mediator = _Mediator()
    loop = _loop(mediator, [_SEARCH, _SEARCH, {"step": "finish"}])
    answers = [ALICE, None]

    result = loop.run(ALICE, "q", refresh_user=lambda: answers.pop(0))

    assert result.gathered, "the work done before the change was thrown away"


def test_no_further_reads_happen_after_the_change():
    # THE PROPERTY THAT MATTERS. Stopping is only meaningful if it
    # stops: a loop that noticed and carried on would read under an
    # authority that no longer holds.
    mediator = _Mediator()
    loop = _loop(mediator, [_SEARCH, _SEARCH, _SEARCH, {"step": "finish"}])
    answers = [ALICE, None]

    loop.run(ALICE, "q", refresh_user=lambda: answers.pop(0))

    assert len(mediator.reads) == 1, f"read {len(mediator.reads)} times after authority changed"


def test_without_a_refresher_the_loop_behaves_as_before():
    # refresh_user is optional: scripts/agent_trace.py and the tests
    # call run() without one, and a missing refresher must not mean
    # "stop immediately".
    mediator = _Mediator()
    loop = _loop(mediator, [_SEARCH, {"step": "finish"}])

    result = loop.run(ALICE, "q")

    assert result.authority_changed is False
    assert mediator.reads
