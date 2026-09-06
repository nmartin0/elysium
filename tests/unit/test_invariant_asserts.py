"""
Tests for the invariant assertions guarding Points 1-3 of the machinery
audit.

WHY ASSERTIONS RATHER THAN RAISES. Each condition below is one the code
believes is IMPOSSIBLE, not one a caller can provoke. A bad argument
gets a real exception with a clear message (this project does that
throughout); an assert marks a place where the program's own reasoning
has broken down, and there is no sensible recovery -- only stopping
before the damage spreads.

They are deliberately placed where silent corruption would otherwise be
UNRECOVERABLE or UNDIAGNOSABLE:
  - a batch marked applied while a sub-write never ran: nothing revisits
    it afterwards, so the loss is permanent
  - a write-log row marked applied with storages unwritten: reads then
    report values that do not exist, with nothing left pending
  - a sync writing a different row count than it read: reports success
    with quietly incomplete data
  - a duplicate in a lock set: threading.Lock is not reentrant, so it
    HANGS rather than raising -- the hardest possible failure to
    diagnose from a stack trace

These run in production because the application REFUSES TO START
without them -- see require_assertions_enabled(), called by both
api/app.py and scripts/run_sync.py.

That guard exists because the original claim here was not verified.
It said nothing runs Python with -O "verified directly", and the check
had covered install/ and scripts/ but not the systemd unit or any
container entrypoint -- the paths that would actually carry the
setting. The claim happened to be true; it was not established. A
guard makes it true by construction rather than by inspection.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.ontology.mediator import DataMediator


def test_a_duplicate_object_in_a_lock_set_is_caught_not_hung():
    # threading.Lock is not reentrant: acquiring the same lock twice in
    # one loop deadlocks the caller against itself, permanently and
    # silently. propose_action() already rejects an action whose
    # sub-writes resolve to the same object, so this is defence in depth
    # for any second path into the locking primitive.
    mediator = DataMediator({}, {}, {}, {})

    with pytest.raises(AssertionError, match="not reentrant"):
        with mediator._locks_for_objects([("Account", "a1"), ("Account", "a1")]):
            pass


def test_distinct_objects_in_a_lock_set_are_fine():
    # The assert must not fire on the normal case -- a multi-object
    # action legitimately locks several distinct objects at once.
    mediator = DataMediator({}, {}, {}, {})

    with mediator._locks_for_objects([("Account", "a1"), ("Account", "a2")]):
        pass


@pytest.fixture
def sync(tmp_path):
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(f"r{i}", f"v{i}") for i in range(4)])
    conn.commit()
    conn.close()
    return IcebergMirrorSync(tmp_path / "mirror", {"p": SQLiteReadAdapter({"path": source})})


def test_a_normal_sync_does_not_trip_the_row_count_assert(sync):
    result = sync.sync_table("p", "t", "id", ["id", "v"])

    assert result.row_count == 4


# --- The guarantee that these run at all ---------------------------------


def test_the_startup_guard_passes_when_assertions_are_enabled():
    from core.sqlite_connection import require_assertions_enabled

    require_assertions_enabled()  # does not raise


def test_the_startup_guard_refuses_when_assertions_are_stripped():
    """Runs a real subprocess under -O, because a test process cannot
    strip its own assertions -- __debug__ is fixed at interpreter
    start. Simulating it by patching a flag would test the simulation,
    not the guard."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-O", "-c",
         "from core.sqlite_connection import require_assertions_enabled;"
         " require_assertions_enabled()"],
        capture_output=True, text=True, cwd=".",
    )

    assert result.returncode != 0
    assert "assertions to be enabled" in result.stderr
    assert "PYTHONOPTIMIZE" in result.stderr, "the message must name the fix"


def test_both_entry_points_call_the_guard():
    # A guard nothing calls is worse than none: it reads as a
    # guarantee while providing nothing. Asserted structurally, since
    # the runtime behaviour needs a separate interpreter.
    assert "require_assertions_enabled()" in open("api/app.py").read()
    assert "require_assertions_enabled()" in open("scripts/run_sync.py").read()


def test_the_refusal_message_names_the_fix():
    # An operator hitting this at 3am needs to know what to change,
    # not merely that something is wrong.
    from core.sqlite_connection import require_assertions_enabled

    source = require_assertions_enabled.__doc__ or ""
    import inspect
    body = inspect.getsource(require_assertions_enabled)

    assert "PYTHONOPTIMIZE" in body
    assert "-O" in body
    assert source
