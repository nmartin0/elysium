"""
Crash recovery finishes a delete -- and never invents a create.

001's F-27, REPRODUCED BEFORE THIS FIX. Both resume dispatches were
two-way over three operations, so a DELETE fell into the create branch
(or the update branch): the delete was lost, recovery reported
{'resumed': 1}, and the write log -- the authority -- gained a 'create'
nobody asked for, because a delete's empty changes passed through
without raising.
"""

import time

import pytest

OBJ = ("Customer", "cust_004")


@pytest.fixture
def wm(client):
    return client.app.state.generation.write_mediator


def _operations(wl):
    return [entry["operation"] for entry in wl.edit_history(*OBJ)]


class TestABatchWhoseDeleteNeverGotItsEntry:
    def test_the_delete_is_finished(self, wm):
        """THE REPRODUCTION: logged in a batch, crashed before the delete's
        own entry was written, then resumed."""
        wl = wm.write_log
        wl.log_pending_batch(
            [{"object_type": OBJ[0], "object_id": OBJ[1], "operation": "delete",
              "changes": {}, "expected_current_values": {}}],
            "alice", "remove the customer")

        report = wm.resume_pending_writes()

        assert wl.is_deleted(*OBJ)
        assert report["resumed"] == 1

    def test_and_the_log_records_a_delete_not_a_create(self, wm):
        """THE FABRICATION was the worst part: rebuild_deleted_index reads
        `operation`, so a false 'create' would have fought the repair."""
        wl = wm.write_log
        wl.log_pending_batch(
            [{"object_type": OBJ[0], "object_id": OBJ[1], "operation": "delete",
              "changes": {}, "expected_current_values": {}}],
            "alice", "remove the customer")
        wm.resume_pending_writes()

        assert _operations(wl) == ["delete"]


def _batch_with_a_delete(wl):
    """A pending batch holding one delete -- how every real write starts.
    Resume walks pending BATCHES; an entry outside one is never resumed,
    and a first version of these tests made exactly that mistake."""
    return wl.log_pending_batch(
        [{"object_type": OBJ[0], "object_id": OBJ[1], "operation": "delete",
          "changes": {}, "expected_current_values": {}}],
        "alice", "remove the customer")


class TestAPendingDeleteEntry:
    def _pending_delete(self, wl):
        batch_id = _batch_with_a_delete(wl)
        return wl.log_pending_update(OBJ[0], OBJ[1], {}, {}, "alice", "remove",
                                     batch_id=batch_id, operation="delete")

    def test_crashed_before_its_index_row(self, wm):
        wl = wm.write_log
        self._pending_delete(wl)

        wm.resume_pending_writes()

        assert wl.is_deleted(*OBJ)
        assert _operations(wl) == ["delete"]

    def test_crashed_after_its_index_row_is_finished_once(self, wm):
        """IDEMPOTENT: the index row was written, the entry never marked."""
        wl = wm.write_log
        log_id = self._pending_delete(wl)
        wl.record_delete(*OBJ, log_id)

        wm.resume_pending_writes()
        wm.resume_pending_writes()

        assert wl.is_deleted(*OBJ)
        assert _operations(wl) == ["delete"]

    def test_a_later_operation_is_not_undone(self, wm):
        """NEVER REORDERED. An update applied AFTER the delete was logged
        decides the object's state; resuming the delete must not undo it."""
        wl = wm.write_log
        self._pending_delete(wl)
        time.sleep(0.01)
        later = wl.log_pending_update(OBJ[0], OBJ[1], {"name": "Back again"},
                                      {}, "bob", "restore", operation="update")
        wl.mark_applied(later)

        wm.resume_pending_writes()

        assert not wl.is_deleted(*OBJ)


class TestTheApplyWindow:
    def test_a_crash_before_marking_leaves_something_to_finish(self, wm, monkeypatch):
        """THE NARROWER WINDOW F-27 NAMED. Marked applied FIRST, a crash
        before the index row left an applied delete that resume SKIPS.
        Marking LAST, a crash there leaves a pending entry resume finds."""
        from core.ontology.write_mediator import SubWrite

        wl = wm.write_log
        real_record = wl.record_delete

        # THE CRASH GOES IN record_delete -- the index row. Under the old
        # order mark_applied had already SUCCEEDED by then: an applied
        # entry, no index row, and resume skipping it. A first version of
        # this test crashed inside mark_applied instead, which under the
        # old order failed BEFORE taking effect, left the entry pending,
        # and let resume finish it -- so it passed against the bug, and a
        # control restoring the old order proved nothing.
        def crash(*_args):
            raise RuntimeError("the process died here")
        monkeypatch.setattr(wl, "record_delete", crash)
        batch_id = _batch_with_a_delete(wl)
        with pytest.raises(RuntimeError):
            wm._apply_one_delete(SubWrite(OBJ[0], OBJ[1], "delete", {}, {}),
                                 batch_id, "alice", "remove")
        monkeypatch.setattr(wl, "record_delete", real_record)

        wm.resume_pending_writes()

        assert wl.is_deleted(*OBJ)
        assert _operations(wl) == ["delete"]


class TestAnUnknownOperation:
    def test_is_refused_rather_than_guessed(self, wm):
        """THE EXPLICIT `else: raise` matters more than the delete branch:
        the next operation added must not repeat this."""
        with pytest.raises(ValueError, match="unknown operation"):
            wm._resume_one_entry({"id": "x", "operation": "rename",
                                  "object_type": OBJ[0], "object_id": OBJ[1]})
