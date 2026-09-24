"""
A write is authorised when it is APPLIED, not only when it is proposed
(004-7).

THE FINDING, reproduced exactly: propose an action while a ticket is
us-west, move the ticket to us-east, and then

    a fresh proposal is REFUSED: 'u' cannot modify this Ticket
    but the OLD proposal APPLIES -> closed

The same action, by the same person, on the same object: refused when
asked now, applied when asked earlier. The approval window is up to
fifteen minutes on this deployment, and a write nobody may make is not
made safe by having been askable before.

WHAT THE AUDIT GOT SLIGHTLY WRONG, and it is worth recording: it says
`proposed_under_generation` "is recorded and never compared". It IS
compared -- confirm already refuses a write whose fields the ontology
no longer declares, and says which generation it was proposed under.
Constraints and approver criteria are re-evaluated at confirm too. The
gap was narrower than described and no less real: everything was
re-checked EXCEPT the security value of the objects.

CHECKED AGAINST THE APPROVER. They are the person deciding now, their
record is live, and Foundry's rule for applying an action is that the
submitter must be able to see the objects it edits. Re-resolving the
PROPOSER from a stored user id would be a different authority question
with its own answer, and would need a directory lookup this layer does
not have.

NO APPROVER MEANS NO CHECK, because there is nothing to check against:
an auto-executing action confirms inside the request that proposed it,
so the propose-time check IS the current one. The window this closes
is the human one, which is the one measured in minutes.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter, SQLiteWriteAdapter
from core.intermediate_layer.auth import UserRecord
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLogWriter
from core.ontology.write_mediator import WriteMediator

SCHEMA = {
    "Ticket": {
        "id_field": "id", "security": {"field": "region"},
        "storage": {"silo": "p", "table": "t", "id_column": "id"},
        "fields": {"id": {"type": "data"}, "status": {"type": "data"},
                    "region": {"type": "data"}},
    }
}
ACTIONS = {
    "close": {
        "display_name": "Close", "description": "d",
        "affected_object_types": ["Ticket"],
        "parameters": {"ticket": {"type": "object_reference", "object_type": "Ticket"}},
        "sub_writes": [{"operation": "update", "object_type": "Ticket",
                         "object_id": "parameter.ticket",
                         "mutations": [{"set": {"property": "status",
                                                 "value": "closed"}}]}],
    }
}
GRANTS = frozenset(["execute:close", "read:Ticket", "read:Ticket.status",
                     "read:Ticket.region", "read:Ticket.id"])
WEST = UserRecord(user_id="u", security_value="us-west", role_name="agent")
EAST = UserRecord(user_id="e", security_value="us-east", role_name="agent")


@pytest.fixture
def deployment(tmp_path):
    source = tmp_path / "s.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, status TEXT, region TEXT)")
    conn.execute("INSERT INTO t VALUES ('t1','open','us-west')")
    conn.commit()
    conn.close()
    roles = {"agent": {"allowed_actions": GRANTS}}
    write_log = WriteLogWriter(tmp_path / "wl.db")
    mediator = DataMediator(SCHEMA, {"p": SQLiteReadAdapter({"path": source})},
                             {"Ticket": "p"}, roles, write_log=write_log)
    writer = WriteMediator(mediator, {"p": SQLiteWriteAdapter({"path": source})},
                            roles, ACTIONS, 1)

    def move_to(region):
        conn = sqlite3.connect(source)
        conn.execute("UPDATE t SET region=? WHERE id='t1'", (region,))
        conn.commit()
        conn.close()

    def status():
        conn = sqlite3.connect(source)
        try:
            return conn.execute("SELECT status FROM t WHERE id='t1'").fetchone()[0]
        finally:
            conn.close()

    writer.move_to, writer.status = move_to, status
    return writer


class TestAnObjectThatMovesOutOfReach:
    def test_the_old_proposal_no_longer_applies(self, deployment):
        """THE REGRESSION TEST for the reproduction above."""
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")
        deployment.move_to("us-east")

        with pytest.raises(PermissionError, match="no longer within reach"):
            deployment.confirm_and_execute(pending, approved=True, approver=WEST)

    def test_nothing_is_written(self, deployment):
        """A refusal that had already written something would be
        worse than no refusal."""
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")
        deployment.move_to("us-east")

        with pytest.raises(PermissionError):
            deployment.confirm_and_execute(pending, approved=True, approver=WEST)

        assert deployment.status() == "open"

    def test_a_fresh_proposal_is_refused_too(self, deployment):
        """The property that makes the old behaviour indefensible: the
        two paths now agree."""
        deployment.move_to("us-east")

        with pytest.raises(PermissionError):
            deployment.propose_action(WEST, "close", {"ticket": "t1"}, origin="human")

    def test_who_APPROVES_does_not_change_the_answer(self, deployment):
        """THE DESIGN DECISION, pinned. The check is about the
        PROPOSER's reach, not the approver's, so an approver in the
        object's new compartment cannot rescue the write either. That
        is deliberate: requiring the APPROVER to reach the object
        would narrow who may sign things off, and this repository
        already has four-eyes tests where a cross-org approver is the
        point. Recorded for the owner rather than changed here."""
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")
        deployment.move_to("us-east")

        with pytest.raises(PermissionError, match="who proposed it"):
            deployment.confirm_and_execute(pending, approved=True, approver=EAST)

    def test_a_cross_compartment_approver_is_still_allowed_in_general(self, deployment):
        """The four-eyes property this must not break: an approver who
        cannot reach the object may still approve a write that is
        otherwise fine. tests/unit/test_write_mediator.py has three
        tests standing on this, and the fixture's own comment calls
        bob's org a "MAC boundary test"."""
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")

        deployment.confirm_and_execute(pending, approved=True, approver=EAST)

        assert deployment.status() == "closed"


class TestTheOrdinaryPathIsUnchanged:
    def test_an_unmoved_object_is_written(self, deployment):
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")

        deployment.confirm_and_execute(pending, approved=True, approver=WEST)

        assert deployment.status() == "closed"

    def test_with_no_approver_it_still_applies(self, deployment):
        """Auto-execute confirms inside the request that proposed it,
        so the propose-time check IS the current one. Requiring an
        approver here would break a path that has no person in it."""
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")

        deployment.confirm_and_execute(pending, approved=True)

        assert deployment.status() == "closed"

    def test_a_rejection_is_still_just_a_rejection(self, deployment):
        """approved=False must not go anywhere near the new check."""
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")
        deployment.move_to("us-east")

        deployment.confirm_and_execute(pending, approved=False, approver=WEST)

        assert deployment.status() == "open"


class TestAnObjectThatIsGone:
    """FOUND BY THE EXISTING DELETE TESTS, not by me. The first
    version refused whenever the object had no security value -- and a
    DELETED object has none, so a write meant to bring one back was
    blocked by a rule about compartments. "Not there" is not "in
    another compartment"."""

    def test_a_write_to_a_deleted_object_is_not_refused_by_this_check(self, deployment):
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")
        conn = sqlite3.connect(deployment.mediator.adapters["p"].db_path)
        conn.execute("DELETE FROM t WHERE id='t1'")
        conn.commit()
        conn.close()

        # Whatever else happens to this write, it is not this check's
        # business: there is no compartment to be outside of.
        try:
            deployment.confirm_and_execute(pending, approved=True, approver=WEST)
        except PermissionError as e:  # pragma: no cover - would be the bug
            assert "no longer within reach" not in str(e)
        except ValueError:
            pass


class TestCreates:
    """WRITTEN BECAUSE A CONTROL PROVED NOTHING. Checking creates as
    well still passed, because no test made one -- and a create is
    exactly the case the skip exists for: the object does not exist
    yet, so it has no security value to be outside of. Without the
    skip, every create would be refused at confirm."""

    def test_a_create_still_applies(self, tmp_path):
        source = tmp_path / "c.db"
        conn = sqlite3.connect(source)
        conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, status TEXT, region TEXT)")
        conn.commit()
        conn.close()
        actions = {
            "open_ticket": {
                "display_name": "Open", "description": "d",
                "affected_object_types": ["Ticket"],
                "parameters": {"ticket": {"type": "string"}},
                "sub_writes": [{"operation": "create", "object_type": "Ticket",
                                 "object_id": "parameter.ticket",
                                 "mutations": [
                                     {"set": {"property": "id", "value": "t9"}},
                                     {"set": {"property": "status", "value": "open"}},
                                     {"set": {"property": "region", "value": "us-west"}}]}],
            }
        }
        roles = {"agent": {"allowed_actions": frozenset(
            ["execute:open_ticket", "read:Ticket", "read:Ticket.status",
             "read:Ticket.region", "read:Ticket.id"])}}
        mediator = DataMediator(SCHEMA, {"p": SQLiteReadAdapter({"path": source})},
                                 {"Ticket": "p"}, roles,
                                 write_log=WriteLogWriter(tmp_path / "cwl.db"))
        writer = WriteMediator(mediator, {"p": SQLiteWriteAdapter({"path": source})},
                                roles, actions, 1)

        pending = writer.propose_action(WEST, "open_ticket", {"ticket": "t9"},
                                         origin="human")
        writer.confirm_and_execute(pending, approved=True, approver=WEST)

        conn = sqlite3.connect(source)
        try:
            assert conn.execute("SELECT status FROM t WHERE id='t9'").fetchone() == ("open",)
        finally:
            conn.close()


class TestItIsRecorded:
    def test_the_refusal_is_audited(self, deployment, tmp_path):
        """A security refusal nobody can see afterwards is half a
        control."""
        pending = deployment.propose_action(WEST, "close", {"ticket": "t1"},
                                             origin="human")
        deployment.move_to("us-east")
        entries = []
        real = deployment.audit_log.log_access

        def spy(*args, **kwargs):
            entries.append(args)
            return real(*args, **kwargs)
        deployment.audit_log.log_access = spy

        with pytest.raises(PermissionError):
            deployment.confirm_and_execute(pending, approved=True, approver=WEST)

        assert any(args[1] == "Ticket" and args[4] is False for args in entries)
