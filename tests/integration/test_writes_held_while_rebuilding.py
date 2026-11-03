"""A write waits while its type is being rebuilt (slice R4 of the retype
design; BLOCKING.md, "RETYPE, CHECKED AND SLICED"), over HTTP.

The rules under test: approving a proposal is the write, and it is HELD with
a 409 that says why while a table the write's type reads is rebuilding (the
Mirror panel's own state: core/mirror/object_state, derived from the last
sync attempt and the sync lock); the proposal STAYS in the queue and the
same approval goes through afterwards; a rejection is never held; a type
whose tables are not rebuilding is not held; and when the state cannot be
told the write is held, never guessed live.
"""

import pytest

from elysium.core.mirror.sync_attempts import SyncAttempts
from elysium.core.mirror.sync_lock import single_writer
from tests.integration.test_approvals_inbox import _csrf, _inbox, _login, _propose

CUSTOMERS = ("primary_sql", "customers")
TRANSACTIONS = ("primary_sql", "transactions")


def _recorded_as_rebuilding(client, table):
    mirror = client.app.state.runtime_paths.data_dir / "mirror"
    mirror.mkdir(parents=True, exist_ok=True)
    SyncAttempts(mirror / "sync_attempts.db").record(*table, "rebuilding")


def _lock(client):
    """A sync holding the lock, as the rebuild does."""
    return single_writer(client.app.state.runtime_paths.data_dir / "sync.lock")


def _decide(client, write_id, approved):
    return client.post(f"/api/writes/{write_id}/confirm", json={"approved": approved}, headers=_csrf(client))


def _name(client):
    return client.get("/api/objects/Customer/cust_001").json()["fields"]["name"]


@pytest.fixture
def proposed(client):
    _login(client, "alice")
    return client, _propose(client)


class TestHeldWhileRebuilding:
    def test_the_approval_is_held_with_the_reason_and_nothing_is_written(self, proposed):
        client, write_id = proposed
        before = _name(client)
        _recorded_as_rebuilding(client, CUSTOMERS)

        with _lock(client) as free:
            assert free
            held = _decide(client, write_id, True)

        assert held.status_code == 409
        assert "Customer is being rebuilt" in held.json()["detail"]
        assert "stays in the queue" in held.json()["detail"]
        assert _name(client) == before

    def test_the_proposal_stays_in_the_queue_and_the_same_approval_goes_through_afterwards(self, proposed):
        client, write_id = proposed
        _recorded_as_rebuilding(client, CUSTOMERS)
        with _lock(client) as free:
            assert free
            assert _decide(client, write_id, True).status_code == 409
            assert [entry["write_id"] for entry in _inbox(client)] == [write_id]

        released = _decide(client, write_id, True)

        assert released.status_code == 200 and released.json()["status"] == "written"
        assert _name(client) == "Ada L."

    def test_a_rejection_is_not_a_write_and_is_not_held(self, proposed):
        client, write_id = proposed
        _recorded_as_rebuilding(client, CUSTOMERS)

        with _lock(client) as free:
            assert free
            rejected = _decide(client, write_id, False)

        assert rejected.status_code == 200
        assert _inbox(client) == []

    def test_a_rebuild_that_died_holds_nothing(self, proposed):
        client, write_id = proposed
        _recorded_as_rebuilding(client, CUSTOMERS)          # recorded, then the process died: no lock

        assert _decide(client, write_id, True).status_code == 200

    def test_a_type_whose_tables_are_not_rebuilding_is_not_held(self, proposed):
        client, write_id = proposed
        _recorded_as_rebuilding(client, TRANSACTIONS)       # another type's table

        with _lock(client) as free:
            assert free
            written = _decide(client, write_id, True)

        assert written.status_code == 200


class TestHeldWhenItCannotBeTold:
    def test_a_mirror_that_cannot_be_read_holds_the_write_and_says_it_cannot_tell(self, proposed, monkeypatch):
        client, write_id = proposed
        before = _name(client)

        def broken(request):
            raise RuntimeError("the catalog cannot be read")

        monkeypatch.setattr("elysium.api.routes._mirror_catalog_for", broken)

        held = _decide(client, write_id, True)

        assert held.status_code == 409
        assert "cannot be told" in held.json()["detail"]
        assert _name(client) == before

    def test_a_lock_that_cannot_be_tried_holds_the_write(self, proposed, monkeypatch):
        client, write_id = proposed
        _recorded_as_rebuilding(client, CUSTOMERS)

        def broken(path):
            raise OSError("no lock")

        monkeypatch.setattr("elysium.core.mirror.sync_lock.single_writer", broken)

        held = _decide(client, write_id, True)

        assert held.status_code == 409 and "cannot be told" in held.json()["detail"]

    def test_a_state_that_cannot_be_worked_out_at_all_holds_the_write(self, proposed, monkeypatch):
        client, write_id = proposed

        def broken(*args, **kwargs):
            raise RuntimeError("no states")

        monkeypatch.setattr("elysium.api.routes._mirror_states", broken)

        assert _decide(client, write_id, True).status_code == 409
