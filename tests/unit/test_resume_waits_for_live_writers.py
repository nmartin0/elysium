"""
Startup resume never takes a write another worker is still applying.

FOUND RUNNING `uvicorn --workers 2` (BLOCKING.md's "--workers for real",
14 Oct) and reproduced with two real processes, which is what these
tests are. Worker A logs a batch and is applying it; worker B starts --
as uvicorn does when it replaces a worker -- and its startup resume
finds the batch pending and applies it. Then A applies it as well:

    B resume {'resumed': 1, ...}
    A raised IntegrityError: UNIQUE constraint failed: t.id

The approver is told the write failed when it was written, and the log
keeps a stray pending row. The object locks could not prevent it: they
are threading.Locks, one set per process.

NOW: applying holds a shared flock beside the write log and resuming an
exclusive one, so a resume waits for every living writer -- and a
writer that DIED released its lock, so its batch is still resumed.
"""

import multiprocessing
import os
import sqlite3
import time
from pathlib import Path

import pytest

from core.ontology import write_mediator as wm
from tests.unit.test_confirming_a_write_rechecks_reach import ACTIONS as BASE
from tests.unit.test_confirming_a_write_rechecks_reach import GRANTS, SCHEMA, WEST

OPEN = {"open_ticket": {
    "display_name": "Open", "description": "d", "affected_object_types": ["Ticket"],
    "parameters": {"ticket": {"type": "string"}},
    "sub_writes": [{"operation": "create", "object_type": "Ticket",
                    "object_id": "parameter.ticket",
                    "mutations": [{"set": {"property": "id", "value": "parameter.ticket"}},
                                  {"set": {"property": "status", "value": "open"}},
                                  {"set": {"property": "region", "value": "us-west"}}]}],
}}


def _writer(tmp: Path) -> "wm.WriteMediator":
    """One worker's view of a deployment that may already exist."""
    from adapters.sqlite_adapter import SQLiteReadAdapter, SQLiteWriteAdapter
    from core.ontology.mediator import DataMediator
    from core.ontology.write_log import WriteLogWriter

    source = tmp / "s.db"
    if not source.exists():
        with sqlite3.connect(source) as conn:
            conn.execute("CREATE TABLE t (id TEXT PRIMARY KEY, status TEXT, region TEXT)")
    roles = {"agent": {"allowed_actions": frozenset(GRANTS | {"execute:open_ticket"})}}
    mediator = DataMediator(SCHEMA, {"p": SQLiteReadAdapter({"path": source})},
                            {"Ticket": "p"}, roles, write_log=WriteLogWriter(tmp / "wl.db"))
    return wm.WriteMediator(mediator, {"p": SQLiteWriteAdapter({"path": source})},
                            roles, {**BASE, **OPEN}, 1)


def _worker_a(tmp, outcome, die):
    """Logs the batch, then is held before applying -- and either
    finishes, or dies there like a killed worker."""
    writer = _writer(Path(tmp))
    real = wm.WriteMediator._apply_one_create

    def slow(self, *args, **kwargs):
        time.sleep(1.5)
        if die:
            os._exit(1)
        return real(self, *args, **kwargs)
    wm.WriteMediator._apply_one_create = slow
    pending = writer.propose_action(WEST, "open_ticket", {"ticket": "t9"}, origin="human")
    try:
        writer.confirm_and_execute(pending, approved=True, approver=WEST)
        outcome.put(("A", "written"))
    except Exception as error:  # noqa: BLE001 - the outcome IS the test
        outcome.put(("A", type(error).__name__))


def _worker_b(tmp, outcome):
    outcome.put(("B", _writer(Path(tmp)).resume_pending_writes()))


def _race(tmp_path, die):
    _writer(tmp_path)
    context = multiprocessing.get_context("fork")
    outcome = context.Queue()
    a = context.Process(target=_worker_a, args=(str(tmp_path), outcome, die))
    a.start()
    time.sleep(0.6)           # A has logged its batch and is mid-apply
    b = context.Process(target=_worker_b, args=(str(tmp_path), outcome))
    b.start()
    b.join(30)
    a.join(30)
    said = {}
    while not outcome.empty():
        who, what = outcome.get()
        said[who] = what
    with sqlite3.connect(tmp_path / "s.db") as conn:
        rows = conn.execute("SELECT count(*) FROM t WHERE id = 't9'").fetchone()[0]
    with sqlite3.connect(tmp_path / "wl.db") as conn:
        pending = conn.execute("SELECT count(*) FROM write_log WHERE status = 'pending'").fetchone()[0]
    return said, rows, pending


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork to run two real workers")
class TestTwoRealWorkers:
    def test_a_live_writers_batch_is_left_to_it(self, tmp_path):
        """THE REGRESSION TEST."""
        said, rows, pending = _race(tmp_path, die=False)

        assert said["A"] == "written"
        assert said["B"]["resumed"] == 0
        assert rows == 1 and pending == 0

    def test_a_dead_writers_batch_is_still_resumed(self, tmp_path):
        """The reason resume exists, which the lock must not break: flock
        is released when its process dies."""
        said, rows, pending = _race(tmp_path, die=True)

        assert "A" not in said, "A was meant to die mid-apply"
        assert said["B"]["resumed"] == 1
        assert rows == 1 and pending == 0
