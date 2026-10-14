"""
A change waiting for approval, shown on the object it would change
(DEV_UI 15.3: "if an object has a pending change, that belongs ON THE
OBJECT; if a set does, it belongs on the set").

The caller sees what the Inbox would show them -- writes they may decide
or proposed -- and only on objects they may read.
"""

from datetime import UTC, datetime

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite
from tests.conftest import with_roles
from tests.integration.test_api import _login  # noqa: F401


def _as(client, username, role):
    client.app.state.user_directory.create_user(username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _waiting(client, *object_ids, proposer="proposer"):
    return client.app.state.pending_writes.store(PendingWrite(
        sub_writes=tuple(SubWrite("Transaction", object_id, "update", {"category": "x"})
                         for object_id in object_ids),
        user_id=proposer, description="Recategorize", action_type_name="Recategorize",
        origin="human", proposed_at=datetime.now(UTC), proposed_under_generation=1,
        parameters={}, proposer=UserRecord(proposer, "customer_service", "us-west")))


def _pending(client, ids):
    response = client.get("/api/writes/pending-for",
                          params={"object_type": "Transaction", "ids": ",".join(ids)})
    assert response.status_code == 200, response.text
    return response.json()["pending"]


def _approver(client):
    roles = client.app.state.generation.config.roles
    with_roles(client.app, approver={"allowed_actions": [
        *roles["customer_service"]["allowed_actions"], "execute:Recategorize"]})
    _as(client, "dana", "approver")


def test_an_object_with_a_change_waiting_says_so(client):
    write_id = _waiting(client, "1")
    _approver(client)

    assert _pending(client, ["1", "2"]) == {"1": [{
        "write_id": write_id, "action_type_name": "Recategorize",
        "awaiting_your_review": True, "proposed_by_you": False}]}


def test_a_set_learns_which_of_its_objects_have_one(client):
    _waiting(client, "1", "3")
    _approver(client)

    assert sorted(_pending(client, ["1", "2", "3", "4"])) == ["1", "3"]


def test_someone_who_may_not_decide_it_and_did_not_propose_it_sees_nothing(client):
    """THE INBOX'S RULE: the object shows nothing the Inbox would hide."""
    _waiting(client, "1")
    _as(client, "erin", "customer_service")

    assert _pending(client, ["1"]) == {}


def test_the_proposer_sees_their_own(client):
    """THE CONTROL for the one above: the same role, now the proposer."""
    _waiting(client, "1", proposer="erin")
    _as(client, "erin", "customer_service")

    assert _pending(client, ["1"])["1"][0]["proposed_by_you"] is True


def test_an_object_they_cannot_read_is_answered_as_nothing_waiting(client):
    """Transaction 5 is cust_003's, us-east; this approver is us-west."""
    _waiting(client, "5")
    _approver(client)

    assert _pending(client, ["5"]) == {}
