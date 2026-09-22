"""
The read-only finder for creates that crash recovery fabricated (F-27).

An applied 'create' with EMPTY changes is a fabrication: a real create
carries its id field. Each marks a delete that recovery lost.
"""

import subprocess
import sys

from core.ontology.write_log import WriteLogWriter
from scripts.find_fabricated_creates import find_fabricated_creates


def _log(tmp_path):
    path = tmp_path / "write_log.db"
    wl = WriteLogWriter(path)
    fabricated = wl.log_pending_update("Customer", "c1", {}, {}, "alice", "remove",
                                       operation="create")
    wl.mark_applied(fabricated)
    real = wl.log_pending_update("Customer", "c2", {"customer_id": "c2", "name": "Ada"}, {},
                                 "bob", "add", operation="create")
    wl.mark_applied(real)
    return path


def test_it_finds_the_fabrication_and_only_that(tmp_path):
    found = find_fabricated_creates(_log(tmp_path))

    assert [(e["object_id"], e["description"]) for e in found] == [("c1", "remove")]


def test_it_changes_nothing(tmp_path):
    """READ-ONLY, byte for byte."""
    path = _log(tmp_path)
    before = path.read_bytes()

    find_fabricated_creates(path)

    assert path.read_bytes() == before


def test_a_missing_log_is_reported_not_created(tmp_path):
    """OPENING A MISSING SQLITE PATH CREATES IT -- a trap recorded in this
    project. mode=ro and an existence check mean it does not."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.find_fabricated_creates", "--data-dir", str(tmp_path)],
        capture_output=True, text=True,
    )

    assert result.returncode == 2
    assert not (tmp_path / "write_log.db").exists()


def test_it_exits_non_zero_when_it_finds_one(tmp_path):
    _log(tmp_path)
    result = subprocess.run(
        [sys.executable, "-m", "scripts.find_fabricated_creates", "--data-dir", str(tmp_path)],
        capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert "LOST DELETE" in result.stdout


def test_empty_changes_are_found_however_they_are_spelled(tmp_path):
    """PARSED, NOT COMPARED AS TEXT -- the docstring's claim, pinned.
    '{ }' is as empty as '{}'."""
    import sqlite3

    path = _log(tmp_path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE write_log SET changes = '{ }' WHERE object_id = 'c1'")
    conn.commit()
    conn.close()

    assert [e["object_id"] for e in find_fabricated_creates(path)] == ["c1"]
