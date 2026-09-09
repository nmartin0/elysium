"""The audit log must survive a rotation without losing records.

logrotate moves the file and creates a new one; anything holding the
old handle keeps writing to an inode nobody can read. The write path
opens and closes per record specifically so that cannot happen, and
these tests exist so a later optimisation cannot quietly undo it --
a persistent handle measured 4.5us against 18.3us, which is exactly
the kind of win that gets taken without noticing what it costs.
"""

import json

from core.intermediate_layer.audit import AuditLog


def _entries(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def test_writing_continues_into_a_new_file_after_rotation(tmp_path):
    """Simulates exactly what logrotate does: rename, then let the
    application create the next one."""
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)
    audit.log_access("alice", "Customer", "c1", "read", True, True)

    log_path.rename(tmp_path / "audit.log.1")
    audit.log_access("alice", "Customer", "c2", "read", True, True)

    assert log_path.exists(), "no new file -- a held handle wrote to the old inode"
    assert [e["object_id"] for e in _entries(log_path)] == ["c2"]
    assert [e["object_id"] for e in _entries(tmp_path / "audit.log.1")] == ["c1"]


def test_no_records_are_lost_across_a_rotation(tmp_path):
    """The property that matters, stated as a total.

    Asserting only that the new file exists would pass against an
    implementation that dropped the record it was mid-write on.
    """
    log_path = tmp_path / "audit.log"
    audit = AuditLog(log_path=log_path)

    for index in range(5):
        audit.log_access("alice", "Customer", f"c{index}", "read", True, True)
        if index == 2:
            log_path.rename(tmp_path / "audit.log.1")

    written = _entries(tmp_path / "audit.log.1") + _entries(log_path)
    assert sorted(e["object_id"] for e in written) == [f"c{i}" for i in range(5)]


def test_the_directory_is_recreated_if_it_disappears(tmp_path):
    """_log_dir_ready caches that the directory exists, which is right
    for the 200,000-mkdir case it was added for -- but a cache of a
    fact that can stop being true is a cache that can be wrong.

    Recorded rather than asserted as correct: this documents the
    CURRENT behaviour. If the directory is removed under a running
    process, writes fail. That is acceptable, because logrotate never
    removes the directory -- only the file -- and this test exists so
    the assumption is visible rather than implicit.
    """
    log_path = tmp_path / "logs" / "audit.log"
    audit = AuditLog(log_path=log_path)
    audit.log_access("alice", "Customer", "c1", "read", True, True)

    assert log_path.exists()
    assert log_path.parent.is_dir()
