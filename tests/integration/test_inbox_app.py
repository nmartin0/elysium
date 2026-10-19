"""
The Inbox: one rail entry for what arrived, and the counts its badge shows.

ONE ENTRY, decided 14 Oct. Approvals, notifications and merge proposals
were three rail entries for one kind of thing -- "events that arrived,
not something being explored" (DEV_UI 12) -- and are now three tabs.

UNGATED. Each tab is the caller's own queue, scoped server-side, so
somebody with nothing waiting sees an empty inbox rather than a
forbidden one -- the uniform denial every read path here uses.

THE COUNTS USE EACH QUEUE'S OWN ELIGIBILITY, so the badge cannot promise
a decision its queue will not show.
"""

import json

from core.identity_decisions import MergeDecisionStore
from core.notifications import NotificationStore
from tests.conftest import with_roles
from tests.integration.test_api import _login  # noqa: F401


def _as(client, username, role="customer_service"):
    client.app.state.user_directory.create_user(
        username, "correct-pw", "us-west", role)
    _login(client, username, "correct-pw")


def _app_paths(client):
    # /me/visible-apps RETURNS A BARE LIST, not an object with an
    # "apps" key -- checked rather than assumed, after a first version
    # guessed the envelope and got KeyError.
    return [app["path"] for app in client.get("/api/me/visible-apps").json()]


class TestOneEntry:
    def test_an_ordinary_user_sees_the_inbox(self, client):
        _as(client, "alice")

        assert "/inbox" in _app_paths(client)

    def test_and_not_its_three_tabs_as_entries_of_their_own(self, client):
        _as(client, "alice")

        paths = _app_paths(client)
        assert not {"/approvals", "/notifications", "/identity"} & set(paths)

    def test_the_lowest_privileged_role_still_sees_it(self, client):
        """SOMEBODY WITH NOTHING WAITING SEES AN EMPTY INBOX, not a
        forbidden one."""
        _as(client, "bob", role="customer_service_link_only")

        assert "/inbox" in _app_paths(client)


def _notes(client):
    return NotificationStore(client.app.state.runtime_paths.data_dir / "notifications.db")


def _merges(client):
    return MergeDecisionStore(client.app.state.runtime_paths.data_dir / "identity_decisions.db")


class TestTheCounts:
    def test_nothing_waiting_is_all_zeros(self, client):
        _as(client, "alice")

        assert client.get("/api/me/inbox").json() == {
            "approvals": 0, "notifications": 0, "identity": 0, "enrichment": 0, "predictions": 0,
            "unusual": 0}

    def test_unseen_notifications_are_counted_and_only_the_callers(self, client):
        _notes(client).notify("alice", "query_answer", "Answer to: one")
        _notes(client).notify("alice", "query_answer", "Answer to: two")
        _notes(client).notify("someone-else", "query_answer", "Answer to: theirs")
        _as(client, "alice")

        assert client.get("/api/me/inbox").json()["notifications"] == 2

    def test_a_merge_counts_only_for_someone_who_may_decide_it(self, client):
        """customer_service reads Customer and may not write it, so the
        proposal is in its queue to see and not to decide: no badge."""
        _merges(client).propose("Customer", "primary:cust_001", "primary:cust_002", 0.9,
                                json.dumps({"name": True}))
        _as(client, "clerk", role="customer_service")

        assert client.get("/api/me/inbox").json()["identity"] == 0

    def test_and_does_count_for_someone_who_may(self, client):
        """THE CONTROL for the one above."""
        _merges(client).propose("Customer", "primary:cust_001", "primary:cust_002", 0.9,
                                json.dumps({"name": True}))
        with_roles(client.app, editor={"allowed_actions": [
            *client.app.state.generation.config.roles["editor"]["allowed_actions"],
            "write:Customer"]})
        _as(client, "carol", role="editor")

        assert client.get("/api/me/inbox").json()["identity"] == 1

    def test_a_merge_whose_side_they_cannot_see_is_not_counted(self, client):
        """cust_003 is us-east: the queue does not list it, so the badge
        must not count it either -- a number they cannot find is a fact
        about a record they may not see."""
        _merges(client).propose("Customer", "primary:cust_001", "primary:cust_003", 0.9, "{}")
        with_roles(client.app, editor={"allowed_actions": [
            *client.app.state.generation.config.roles["editor"]["allowed_actions"],
            "write:Customer"]})
        _as(client, "carol", role="editor")

        assert client.get("/api/me/inbox").json()["identity"] == 0


def _waiting_write(client, action="Recategorize"):
    from datetime import UTC, datetime

    from core.intermediate_layer.auth import UserRecord
    from core.ontology.write_mediator import PendingWrite, SubWrite

    return client.app.state.pending_writes.store(PendingWrite(
        sub_writes=(SubWrite("Transaction", "1", "update", {"category": "x"}),),
        user_id="proposer", description="Recategorize 1", action_type_name=action,
        origin="human", proposed_at=datetime.now(UTC), proposed_under_generation=1,
        parameters={}, proposer=UserRecord("proposer", "customer_service", "us-west")))


class TestTheApprovalsCount:
    def test_a_write_counts_for_someone_who_may_execute_its_action(self, client):
        with_roles(client.app, approver={"allowed_actions": ["read:Customer", "execute:Recategorize"]})
        _waiting_write(client)
        _as(client, "dana", role="approver")

        assert client.get("/api/me/inbox").json()["approvals"] == 1

    def test_and_not_for_someone_who_may_not(self, client):
        """THE CONTROL: the same write, a role without the grant."""
        with_roles(client.app, approver={"allowed_actions": ["read:Customer"]})
        _waiting_write(client)
        _as(client, "dana", role="approver")

        assert client.get("/api/me/inbox").json()["approvals"] == 0


class TestNotificationDoors:
    """DEV_UI 12: every inbox row a door. An answer carries the objects it
    was built from -- only those the reader may still read."""

    def test_an_answer_names_the_objects_it_read(self, client):
        _notes(client).notify("alice", "query_answer", "Answer to: Ada?",
                              subjects=[("Customer", "cust_001")])
        _as(client, "alice")

        (row,) = client.get("/api/notifications").json()["notifications"]
        assert row["subjects"] == [{"object_type": "Customer", "object_id": "cust_001"}]

    def test_one_they_can_no_longer_read_is_not_named(self, client):
        """cust_003 is us-east: read once, say, before a region moved --
        a link to it now would say it exists."""
        _notes(client).notify("alice", "query_answer", "Answer to: two?",
                              subjects=[("Customer", "cust_001"), ("Customer", "cust_003")])
        _as(client, "alice")

        (row,) = client.get("/api/notifications").json()["notifications"]
        assert [door["object_id"] for door in row["subjects"]] == ["cust_001"]
