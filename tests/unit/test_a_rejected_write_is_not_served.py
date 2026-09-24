"""
A write that was REFUSED is never served as the object's value
(PA001-A3).

THE COMMENT SAID THE RIGHT THING AND THE CODE DID ANOTHER. When the
optimistic check refuses a write -- the value changed since it was
proposed -- the call site said:

    # NOTHING in this entry committed, so the log row is abandoned
    # rather than left pending. Without this, a rejected write leaves
    # a row that get_field()'s own write-log masking keeps reporting
    # as the object's value -- a read showing a number that was never
    # written, indefinitely.

and then called mark_APPLIED. `applied` is precisely what the mirror
overlay, edit_history and edits_touching_field read, so the refused
write became the object's value by the same masking the comment was
describing.

MEASURED: two transfers, the second refused. The database holds 900.
The overlay served 800, edit_history listed 800 first, and
edits_touching_field counted two applied writes.

SO IT GETS THE WORD THE COMMENT ALREADY USED. Neither `pending` nor
`applied` is true of a refused entry: pending means "still coming",
applied means "this is the value". Abandoned means neither, which is
exactly the state.
"""

import pytest

from core.ontology.write_log import WriteLogWriter
from tests.unit.test_write_path_atomicity import (
    ACCOUNTANT,
    _raw,
    _transfer,
)
from tests.unit.test_write_path_atomicity import (
    deployment as _atomicity_deployment,
)


@pytest.fixture
def deployment(tmp_path):
    """The write-path fixture from test_write_path_atomicity, reused.

    FORWARDED RATHER THAN IMPORTED DIRECTLY: importing a fixture and
    then naming it as a parameter reads to the linter as redefining
    it, and silencing that would hide real shadowing elsewhere.
    """
    return _atomicity_deployment.__wrapped__(tmp_path)

SINCE = "2000-01-01T00:00:00+00:00"


@pytest.fixture
def written_log(tmp_path):
    written = WriteLogWriter(tmp_path / "wl.db")
    applied = written.log_pending_update("Account", "acc1", {"balance": 900},
                                          {"balance": 1000}, "u", "transfer 1")
    written.mark_applied(applied)
    refused = written.log_pending_update("Account", "acc1", {"balance": 800},
                                          {"balance": 1000}, "u", "transfer 2")
    written.mark_abandoned(refused)
    return written


class TestARefusedWriteIsInvisibleToReaders:
    def test_the_mirror_overlay_serves_the_applied_value(self, written_log):
        """THE REGRESSION TEST: the overlay served 800, a number the
        database never held."""
        assert written_log.get_applied_changes_since("Account", "acc1", SINCE) == {"balance": 900}

    def test_edit_history_does_not_list_it(self, written_log):
        """A person reading the history of an object should not be
        shown a change that was refused as though it happened."""
        changes = [entry.get("changes") for entry in
                   written_log.edit_history("Account", "acc1")]

        assert changes == [{"balance": 900}]

    def test_it_is_not_counted_as_an_edit_touching_the_field(self, written_log):
        """This count decides whether the drift policy REFUSES a
        removed column (PA001-A1). A refused write counting as a
        reason to refuse would hold a schema change hostage to
        something that never happened."""
        assert written_log.edits_touching_field("Account", "balance") == {"applied": 1,
                                                                   "pending": 0}


class TestTheOtherStatesAreUnchanged:
    def test_a_pending_write_is_still_pending(self, tmp_path):
        written = WriteLogWriter(tmp_path / "p.db")
        written.log_pending_update("Account", "acc1", {"balance": 700},
                                    {"balance": 1000}, "u", "waiting")

        assert written.edits_touching_field("Account", "balance") == {"applied": 0,
                                                                       "pending": 1}

    def test_an_applied_write_is_still_served(self, tmp_path):
        written = WriteLogWriter(tmp_path / "a.db")
        entry = written.log_pending_update("Account", "acc1", {"balance": 900},
                                            {"balance": 1000}, "u", "t")
        written.mark_applied(entry)

        assert written.get_applied_changes_since("Account", "acc1", SINCE) == {
            "balance": 900}

    def test_abandoning_one_entry_leaves_others_alone(self, tmp_path):
        written = WriteLogWriter(tmp_path / "m.db")
        keep = written.log_pending_update("Account", "acc1", {"tier": "gold"},
                                           {"tier": "silver"}, "u", "keep")
        written.mark_applied(keep)
        drop = written.log_pending_update("Account", "acc1", {"balance": 800},
                                           {"balance": 1000}, "u", "drop")

        written.mark_abandoned(drop)

        assert written.get_applied_changes_since("Account", "acc1", SINCE) == {
            "tier": "gold"}


class TestThroughTheRealWritePath:
    """The audit's P14, end to end: the refusal comes from the
    optimistic check inside the real mediator, not from calling
    mark_abandoned by hand."""

    def test_a_refused_transfer_is_not_served(self, deployment):
        mediator, write_mediator, log, db = deployment
        # Mirror mode, so the overlay is what answers a read -- which
        # is where the refused value was surfacing.
        mediator.mirror_synced_at = "2000-01-01T00:00:00+00:00"
        first = _transfer(write_mediator, from_balance=900)
        second = _transfer(write_mediator, from_balance=800)
        write_mediator.confirm_and_execute(first, approved=True)

        with pytest.raises(ValueError, match="changed since"):
            write_mediator.confirm_and_execute(second, approved=True)

        served = mediator.get_field(ACCOUNTANT, "Account", "acc_checking", "balance")
        assert float(served) == _raw(db, "acc_checking") == 900.0

    def test_the_refused_entry_is_recorded_as_abandoned(self, deployment):
        """Not deleted: the attempt happened and the log is
        append-only. It simply is not a value."""
        mediator, write_mediator, log, db = deployment
        first = _transfer(write_mediator, from_balance=900)
        second = _transfer(write_mediator, from_balance=800)
        write_mediator.confirm_and_execute(first, approved=True)
        with pytest.raises(ValueError):
            write_mediator.confirm_and_execute(second, approved=True)

        import sqlite3
        conn = sqlite3.connect(log.db_path)
        try:
            statuses = sorted(row[0] for row in
                              conn.execute("SELECT status FROM write_log"))
        finally:
            conn.close()

        # A transfer touches TWO accounts, so the counts depend on how
        # far the refused entry got. The property is the one that
        # matters: the refusal left an `abandoned` row, and nothing
        # sits in `pending` waiting to be masked over reads for ever.
        assert "abandoned" in statuses
        assert "pending" not in statuses
