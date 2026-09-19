"""
The approval queue survives a restart.

THE PRODUCT CLAIM THIS DEFENDS. Elysium's pitch is that writes are
mediated and approved. Losing the queue on deploy was the worst
possible fit between that claim and the behaviour -- and the store's
own docstring said so, as a stated limitation rather than an
oversight.

WRITE-THROUGH, NOT A REPLACEMENT. The locked dict stays the working
store, so reads answer at memory speed; only restarts read from disk.
Reading from SQLite directly would have meant turning eight call sites
under one lock -- several inside a context manager that reserves a
write and may hand it back -- into transactions, rewriting concurrency
this store already gets right.

A RESTORED WRITE IS A PROPOSAL, NOT AN APPROVAL. Everything about
whether it may now execute is asked again at confirm time against the
CURRENT configuration: `confirm` authorises against the current
generation's roles, MAC and the criteria are evaluated inside
`confirm_and_execute()`, and `_fields_no_longer_declared()` refuses
one whose target fields the ontology has since dropped.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore


def _a_write(description="move the money"):
    return PendingWrite(
        sub_writes=(
            SubWrite("Customer", "c1", "update", {"name": "x"}, {"name": "y"}),
        ),
        user_id="alice",
        description=description,
        action_type_name="Rename",
        origin="human",
        proposed_at=datetime.now(UTC),
        proposed_under_generation=7,
        parameters={},
        proposer=UserRecord("alice", "us-west", "editor"),
    )


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "pending.db"


def _store(db_path, ttl=timedelta(minutes=15)):
    """A fresh store against the same file -- which is what a restart
    is, from this store's point of view."""
    return PendingWriteStore(ttl=ttl, persistence=PendingWritePersistence(db_path))


class TestAWriteSurvives:
    def test_it_is_still_awaiting_after_a_restart(self, db_path):
        _store(db_path).store(_a_write())

        assert len(_store(db_path).awaiting(lambda p: True)) == 1

    def test_its_content_survives_intact(self, db_path):
        _store(db_path).store(_a_write("move the money"))

        _, restored = _store(db_path).awaiting(lambda p: True)[0]

        assert restored.description == "move the money"
        assert restored.sub_writes[0].object_id == "c1"
        assert restored.proposer.security_value == "us-west"

    def test_per_task_decisions_survive(self, db_path):
        """DECISIONS ACCUMULATE AGAINST A WRITE. A fifty-task request
        may collect decisions from several reviewers over minutes, and
        losing them would send everyone back to the start of a queue
        they had already worked through."""
        first = _store(db_path)
        write_id = first.store(_a_write())
        first.record_task_decision(write_id, 0, "bob", approved=True)

        second = _store(db_path)
        restored_id, _ = second.awaiting(lambda p: True)[0]

        assert second.task_decisions(restored_id)[0].approver_user_id == "bob"


class TestWhatDoesNotSurvive:
    def test_an_expired_write_is_not_restored(self, db_path):
        """A WRITE WHOSE TTL PASSED WHILE THE SERVICE WAS DOWN has
        expired as surely as one that expired while it was up.

        THE FILTER IN load() IS BELT-AND-BRACES, and this test pins
        the OUTCOME rather than that filter.

        Two attempts to make a control on it fire both failed, and the
        reason is the useful part: `awaiting()` calls
        `_expire_stale_locked()` before returning anything, so a stale
        row restored from disk is evicted on the way out whatever
        load() did. Removing load()'s filter changes nothing
        observable.

        That is worth knowing rather than engineering around -- the
        guarantee comes from the in-memory sweep, and load() skipping
        expired rows merely avoids restoring what is about to be
        thrown away.
        """
        import sqlite3

        _store(db_path).store(_a_write("live"))

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO pending_writes (write_id, owner_user_id, expires_at, "
            "payload) SELECT 'stale', owner_user_id, ?, payload "
            "FROM pending_writes LIMIT 1",
            ((datetime.now(UTC) - timedelta(hours=1)).isoformat(),),
        )
        conn.commit()
        conn.close()

        awaiting = _store(db_path).awaiting(lambda p: True)

        assert len(awaiting) == 1

    def test_a_write_in_a_shape_this_build_cannot_read_is_dropped(self, db_path):
        """ONE UNREADABLE ROW COSTS ITS OWN WRITE, not the queue. A
        restart that dropped every pending approval because one was
        written by an older build would be worse than the problem being
        solved."""
        import sqlite3

        good = _store(db_path)
        good.store(_a_write("readable"))

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO pending_writes (write_id, owner_user_id, expires_at, "
            "payload) VALUES ('broken', 'alice', ?, '{\"schema_version\": 999}')",
            ((datetime.now(UTC) + timedelta(minutes=15)).isoformat(),),
        )
        conn.commit()
        conn.close()

        awaiting = _store(db_path).awaiting(lambda p: True)

        assert len(awaiting) == 1
        assert awaiting[0][1].description == "readable"


class TestPersistenceIsOptional:
    def test_a_store_without_it_works_exactly_as_before(self):
        """EVERY TEST PREDATING THIS GETS None, and the store behaves
        as it always did -- which is what makes this additive rather
        than a rewrite."""
        store = PendingWriteStore(ttl=timedelta(minutes=15))
        write_id = store.store(_a_write())

        assert store.awaiting(lambda p: True)
        assert store.task_decisions(write_id) == {}

    def test_a_broken_persistence_does_not_break_the_store(self, tmp_path):
        """BEST-EFFORT, DELIBERATELY. A proposal that cannot be written
        to disk is still a proposal somebody made; refusing it would
        turn a storage problem into a service outage. The accepted
        failure is losing that one write on a restart -- which is what
        happens today for all of them."""
        unwritable = tmp_path / "no" / "such" / "dir" / "pending.db"
        store = PendingWriteStore(
            ttl=timedelta(minutes=15),
            persistence=PendingWritePersistence(unwritable),
        )

        assert store.store(_a_write())
        assert len(store.awaiting(lambda p: True)) == 1
