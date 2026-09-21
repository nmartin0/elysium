"""
A write proposed in one process is visible in another.

THE TEST THAT WOULD HAVE CAUGHT THIS. The store used to keep writes in
a locked dict, mirrored to disk and read back ONLY AT STARTUP. Every
concurrency test ran THREADS in one process, which that design handled
correctly -- and none ran a second process, which it could not.

A sync started by cron is a second process. A trigger firing during it
would propose a write the running API never saw until restarted.

SO THESE RUN A REAL SECOND INTERPRETER, via subprocess. Threads share
the dict and would pass against the old design; only a separate
process proves the database is the source of truth.
"""

import subprocess
import sys
import textwrap
from datetime import timedelta

from core.intermediate_layer.auth import UserRecord
from core.ontology.write_mediator import PendingWrite, SubWrite
from core.pending_write_persistence import PendingWritePersistence
from core.pending_write_store import PendingWriteStore


def _in_another_process(db_path, body: str) -> str:
    """Runs `body` in a FRESH interpreter against the same database."""
    script = textwrap.dedent(f"""
        from datetime import UTC, datetime, timedelta
        from pathlib import Path
        from core.intermediate_layer.auth import UserRecord
        from core.ontology.write_mediator import PendingWrite, SubWrite
        from core.pending_write_persistence import PendingWritePersistence
        from core.pending_write_store import PendingWriteStore

        store = PendingWriteStore(
            ttl=timedelta(minutes=15),
            persistence=PendingWritePersistence(Path({str(db_path)!r})),
        )
        def a_write(description):
            return PendingWrite(
                sub_writes=(SubWrite("Customer", "c1", "update",
                                     {{"name": "x"}}, {{"name": "y"}}),),
                user_id="alice", description=description,
                action_type_name="Rename", origin="automation",
                proposed_at=datetime.now(UTC), proposed_under_generation=1,
                parameters={{}}, proposer=UserRecord("alice", "us-west", "editor"),
            )
    """) + textwrap.dedent(body)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _store(db_path):
    return PendingWriteStore(
        ttl=timedelta(minutes=15), persistence=PendingWritePersistence(db_path),
    )


class TestASecondProcessIsSeen:
    def test_a_write_proposed_elsewhere_appears_here(self, tmp_path):
        """THE BUG. Build the store HERE first, so an in-memory design
        would already have read the file -- then propose from another
        process, and ask again."""
        db = tmp_path / "pending.db"
        here = _store(db)
        assert here.awaiting(lambda p: True) == []

        _in_another_process(db, 'store.store(a_write("from cron"))')

        awaiting = here.awaiting(lambda p: True)
        assert [pending.description for _, pending in awaiting] == ["from cron"]

    def test_a_decision_made_elsewhere_is_seen_here(self, tmp_path):
        db = tmp_path / "pending.db"
        here = _store(db)
        write_id = _in_another_process(
            db, 'print(store.store(a_write("to approve")))',
        )

        _in_another_process(
            db, f'store.record_task_decision({write_id!r}, 0, "bob", True)',
        )

        assert here.is_fully_approved(write_id)


class TestOnlyOneProcessMayClaim:
    def test_a_write_claimed_elsewhere_cannot_be_claimed_here(self, tmp_path):
        """THE CLAIM IS ONE SQL STATEMENT, and that is what makes it
        safe across processes: `UPDATE ... WHERE reserved = 0` either
        takes the row or matches nothing."""
        db = tmp_path / "pending.db"
        here = _store(db)
        write_id = _in_another_process(db, 'print(store.store(a_write("w")))')

        _in_another_process(db, f"""
            import sqlite3
            conn = sqlite3.connect({str(db)!r})
            conn.execute("UPDATE pending_writes SET reserved = 1 WHERE write_id = ?",
                         ({write_id!r},))
            conn.commit()
        """)

        with here.reserved(write_id, lambda p: True) as pending:
            assert pending is None

    def test_a_reserved_write_is_not_offered_here(self, tmp_path):
        db = tmp_path / "pending.db"
        here = _store(db)
        write_id = _in_another_process(db, 'print(store.store(a_write("w")))')
        _in_another_process(db, f"""
            import sqlite3
            conn = sqlite3.connect({str(db)!r})
            conn.execute("UPDATE pending_writes SET reserved = 1 WHERE write_id = ?",
                         ({write_id!r},))
            conn.commit()
        """)

        assert here.awaiting(lambda p: True) == []


class TestTheRaceBetweenCheckAndClaim:
    def test_a_row_reserved_after_the_check_fails_to_claim(self, tmp_path):
        """THE WINDOW THE SQL GUARD EXISTS FOR, and the only place it
        matters.

        `reserved()` reads the row and checks its flag in Python before
        claiming, so a row ALREADY reserved is refused there -- which is
        why a control deleting `AND reserved = 0` from the UPDATE passed
        every other test in this file.

        The guard is for the RACE: another process reserving the row
        AFTER the check and BEFORE the claim. This stages exactly that
        by making the check see a stale "not reserved" while the
        database says otherwise -- the state a real race produces.
        """
        db = tmp_path / "pending.db"
        here = _store(db)
        write_id = here.store(_pending())
        stale_read = here._load

        def reserved_by_somebody_else_in_between(conn, wid):
            loaded = stale_read(conn, wid)
            conn.execute(
                "UPDATE pending_writes SET reserved = 1 WHERE write_id = ?",
                (wid,),
            )
            conn.commit()
            return loaded[0], False     # the check saw it free

        here._load = reserved_by_somebody_else_in_between

        with here.reserved(write_id, lambda p: True) as pending:
            assert pending is None


class TestADecidedWriteNeverReturns:
    def test_a_committed_write_is_gone_everywhere(self, tmp_path):
        """THE ZOMBIE THE OLD DESIGN WOULD HAVE NEEDED TOMBSTONES FOR.
        Merging another process's rows into memory would bring back a
        decided write whose delete had failed. With no second copy,
        there is nothing to bring back."""
        db = tmp_path / "pending.db"
        here = _store(db)
        write_id = here.store(_pending())

        with here.reserved(write_id, lambda p: True) as pending:
            assert pending is not None

        seen_elsewhere = _in_another_process(
            db, "print(len(store.awaiting(lambda p: True)))",
        )
        assert seen_elsewhere == "0"


def _pending():
    from datetime import UTC, datetime

    return PendingWrite(
        sub_writes=(SubWrite("Customer", "c1", "update", {"name": "x"}, {"name": "y"}),),
        user_id="alice", description="local", action_type_name="Rename",
        origin="human", proposed_at=datetime.now(UTC),
        proposed_under_generation=1, parameters={},
        proposer=UserRecord("alice", "us-west", "editor"),
    )
