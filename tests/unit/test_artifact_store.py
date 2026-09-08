"""
The artifact store: saved searches, saved selections, pending writes.

One store for anything a user saves and may reopen. Saved searches
need it and the Approvals inbox needs it, and both were blocked on the
same three questions -- who may see whose, what expiry means, and what
happens when permissions change -- so they are answered once.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core.artifact_store import ArtifactStore


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path / "artifacts.db")


# --- Ownership is by role ------------------------------------------------


def test_an_owner_sees_their_own_private_artifact(store):
    artifact_id = store.save("saved_search", "Mine", "alice", {"conditions": []})

    assert store.get(artifact_id, "alice", "customer_service") is not None


def test_nobody_else_sees_a_private_artifact(store):
    artifact_id = store.save("saved_search", "Mine", "alice", {"conditions": []})

    assert store.get(artifact_id, "bob", "customer_service") is None


def test_sharing_is_to_a_ROLE_not_a_user(store):
    # Sharing to individuals would be a second permission model beside
    # RBAC, and two models is how permission bugs happen. Roles are
    # already the unit of authorization everywhere else.
    artifact_id = store.save(
        "saved_search", "Team", "alice", {}, shared_role="customer_service"
    )

    assert store.get(artifact_id, "bob", "customer_service") is not None
    assert store.get(artifact_id, "bob", "accountant") is None


def test_a_roleless_caller_does_not_match_a_private_artifact(store):
    """The comparison that would have leaked everything.

    A private artifact stores shared_role as NULL. A caller with no
    role has role_name None. Comparing them directly makes None == None
    true, which would show every private artifact in the deployment to
    anyone without a role.
    """
    artifact_id = store.save("saved_search", "Private", "alice", {})

    assert store.get(artifact_id, "carol", None) is None


def test_a_listing_shows_owned_and_shared_and_nothing_else(store):
    store.save("saved_search", "Mine", "alice", {})
    store.save("saved_search", "Team", "alice", {}, shared_role="customer_service")
    store.save("saved_search", "Bob's", "bob", {})

    titles = {a.title for a in store.list_for("bob", "customer_service")}

    assert titles == {"Team", "Bob's"}


def test_a_listing_can_be_narrowed_to_one_kind(store):
    store.save("saved_search", "A search", "alice", {})
    store.save("saved_selection", "A selection", "alice", {})

    assert [a.title for a in store.list_for("alice", None, kind="saved_search")] == [
        "A search"
    ]


# --- Denial is uniform ---------------------------------------------------


def test_an_artifact_you_may_not_see_is_indistinguishable_from_one_that_does_not_exist(
    store,
):
    # Otherwise being refused an id tells you it exists -- the same
    # oracle an unreadable field would be if it failed differently from
    # an absent one.
    theirs = store.save("saved_search", "Theirs", "alice", {})

    assert store.get(theirs, "bob", "accountant") is None
    assert store.get("no-such-id", "bob", "accountant") is None


# --- Sharing grants reading, not destruction -----------------------------


def test_only_the_owner_may_delete(store):
    artifact_id = store.save(
        "saved_search", "Team", "alice", {}, shared_role="customer_service"
    )

    # Someone who can SEE it cannot remove it out from under its owner.
    assert store.delete(artifact_id, "bob") is False
    assert store.get(artifact_id, "bob", "customer_service") is not None

    assert store.delete(artifact_id, "alice") is True
    assert store.get(artifact_id, "alice", "customer_service") is None


# --- Expiry belongs to the artifact type ---------------------------------


def test_an_artifact_with_no_expiry_never_expires(store):
    # A saved search should outlive the session that made it. NULL is a
    # legitimate answer, not a missing one.
    artifact_id = store.save("saved_search", "Forever", "alice", {})

    assert store.get(artifact_id, "alice", None) is not None


def test_an_expired_artifact_is_gone(store):
    artifact_id = store.save(
        "pending_write", "Stale", "alice", {},
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    assert store.get(artifact_id, "alice", None) is None


def test_an_unexpired_artifact_survives(store):
    artifact_id = store.save(
        "pending_write", "Fresh", "alice", {},
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
    )

    assert store.get(artifact_id, "alice", None) is not None


def test_two_kinds_can_have_opposite_lifetimes_in_one_store(store):
    """The reason expiry is the caller's to set.

    A pending write dies in fifteen minutes because it continues a
    session; a saved search never should. If the store owned expiry,
    every future artifact would inherit a policy designed for one of
    them.
    """
    search = store.save("saved_search", "Kept", "alice", {})
    pending = store.save(
        "pending_write", "Dropped", "alice", {},
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert store.get(search, "alice", None) is not None
    assert store.get(pending, "alice", None) is None


# --- It survives a restart -----------------------------------------------


def test_artifacts_outlive_the_process(tmp_path):
    # The whole point of persisting: the in-memory pending-write store
    # loses everything on restart, which is why an Approvals inbox
    # could not be built on it.
    path = tmp_path / "artifacts.db"
    artifact_id = ArtifactStore(path).save("saved_search", "Durable", "alice", {})

    reopened = ArtifactStore(path).get(artifact_id, "alice", None)

    assert reopened is not None
    assert reopened.title == "Durable"


# --- The body is opaque --------------------------------------------------


def test_the_body_round_trips_unchanged(store):
    # The store has no schema per kind, deliberately: giving it one
    # would make it the place every new artifact type has to change.
    body = {"conditions": [{"field": "region", "operator": "in", "value": ["a", "b"]}]}
    artifact_id = store.save("saved_search", "Filtered", "alice", body)

    assert store.get(artifact_id, "alice", None).body == body
