"""
Tests for PendingWrite's provenance fields -- origin and proposed_at.

WHAT THESE PROTECT, and why user_id was not already enough: both paths
that reach propose_action() set user_id to the same person. A person
filling in ActionForm and the agent choosing an action mid-query are
indistinguishable without origin, and an approvals inbox has to tell a
reviewer which happened. See UI_ROADMAP.md's approvals design record.

The agent-path test deliberately goes through AgentLoop rather than
calling propose_action("agent") directly. Passing the literal myself
would assert that a string I just wrote is the string I just wrote --
the real claim is that the AGENT'S OWN call site passes it, which only
a test that never mentions "agent" on the way in can show.
"""

from datetime import UTC, datetime

import pytest

from core.ontology.write_mediator import PendingWrite
from tests.unit.test_agent_object_query import ACCOUNTANT, TRANSFER, write_loop  # noqa: F401
from tests.unit.test_write_mediator import _record, wm  # noqa: F401  (fixture imports)

RENAME = {"author_id": "auth_001", "new_name": "Ada L."}


def test_a_directly_proposed_write_records_a_human_origin(wm):  # noqa: F811
    pending = wm.propose_action(_record("alice"), "RenameAuthor", RENAME, origin="human")
    assert pending.origin == "human"


def test_origin_has_no_default_and_omitting_it_is_an_error(wm):  # noqa: F811
    # The fail-safe property, and the whole reason origin is required:
    # a default would write a guess into the audit trail. There is no
    # safe guess -- "human" understates the agent, "agent" libels a
    # person -- so the call must not compile rather than lie.
    with pytest.raises(TypeError):
        wm.propose_action(_record("alice"), "RenameAuthor", RENAME)


def test_proposed_at_is_recorded_as_an_aware_utc_instant(wm):  # noqa: F811
    before = datetime.now(UTC)
    pending = wm.propose_action(_record("alice"), "RenameAuthor", RENAME, origin="human")
    after = datetime.now(UTC)
    # Aware, not naive: this timestamp is compared against others
    # across a deployment, and a naive one silently means "whatever
    # the server's local zone was."
    assert pending.proposed_at.tzinfo is not None
    assert before <= pending.proposed_at <= after


def test_provenance_reaches_the_audit_log_not_just_the_object(wm, tmp_path):  # noqa: F811
    # The object is in-process and dies with it. The audit log is
    # where provenance has to survive, so assert on the log, not on
    # the dataclass a second time.
    from core.intermediate_layer.audit import AuditLog

    log_path = tmp_path / "audit.log"
    wm.mediator.audit_log = AuditLog(log_path)
    pending = wm.propose_action(_record("alice"), "RenameAuthor", RENAME, origin="human")
    wm.confirm_and_execute(pending, approved=True)

    written = log_path.read_text()
    assert '"origin": "human"' in written
    assert '"proposed_at"' in written


def test_pending_write_cannot_be_built_without_provenance():
    # Guards the dataclass itself, not just propose_action(): a future
    # caller constructing one directly gets the same requirement.
    with pytest.raises(TypeError):
        PendingWrite((), "alice", "desc", "RenameAuthor")


def test_a_write_the_agent_chose_records_an_agent_origin(write_loop):  # noqa: F811
    # Goes through AgentLoop's real step dispatch. "agent" appears
    # nowhere in the inputs -- the loop's own call site is what has to
    # supply it, and asserting on a literal I passed in myself would
    # prove nothing about that.
    loop, mediator = write_loop()
    gathered: list[dict] = []

    _c, _b, _f, pending = loop._execute_step(
        TRANSFER, ACCOUNTANT, mediator.visible_schema(ACCOUNTANT), gathered, 0, 0,
    )

    assert pending is not None, "expected a proposal to pause for confirmation"
    assert pending.origin == "agent"


def test_the_same_user_gets_different_origins_by_path(write_loop):  # noqa: F811
    # The distinction that user_id alone could not make. One person,
    # two routes, two records -- this is the whole point of the field,
    # and it fails if either call site is wrong.
    loop, mediator = write_loop()
    gathered: list[dict] = []
    _c, _b, _f, from_agent = loop._execute_step(
        TRANSFER, ACCOUNTANT, mediator.visible_schema(ACCOUNTANT), gathered, 0, 0,
    )
    from_person = loop.write_mediator.propose_action(
        ACCOUNTANT, "TransferFunds", TRANSFER["parameters"], origin="human",
    )

    assert from_agent.user_id == from_person.user_id
    assert from_agent.origin != from_person.origin
