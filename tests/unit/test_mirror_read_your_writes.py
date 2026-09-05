"""
Tests for the mirror read-your-writes overlay -- the final piece of
Phase 4 (see ROADMAP.md).

THE PROBLEM, found by testing rather than assumed: after a confirmed
write, the customer's real database genuinely holds the new value, but
the local mirror is a point-in-time copy that hasn't been re-synced.
So a person approves a change and doesn't see it until the next
scheduled sync.

WHY THE EXISTING MASKING COULDN'T SOLVE IT, which is the finding that
shaped this design: WriteLog's get_pending_changes() masks writes that
are still IN FLIGHT. Once confirm_and_execute() succeeds the entry is
marked applied and the pending list is empty -- there is nothing left
to mask. The two mechanisms answer genuinely different questions and
are kept genuinely separate.

The tests below deliberately assert BOTH that the overlay works and
that it stays bounded (a re-sync clears it) and non-invasive (crash
recovery and in-flight masking are unaffected).
"""

import json

import pytest

from core.ontology.write_log import WriteLogWriter


@pytest.fixture
def log(tmp_path):
    return WriteLogWriter(tmp_path / "write_log.db")


def _apply(log, object_type, object_id, changes):
    """Log an update and mark it applied -- the real post-confirm state."""
    log_id = log.log_pending_update(
        object_type, object_id, changes, {}, "alice", "desc"
    )
    log.mark_applied(log_id)
    return log_id


def test_an_applied_write_is_invisible_to_the_in_flight_masking(log):
    # The premise of the whole design: get_pending_changes() genuinely
    # cannot serve read-your-writes, because an applied write is no
    # longer pending. Proven, not assumed.
    _apply(log, "Account", "acc_1", {"balance": 900})

    assert log.get_pending_changes("Account", "acc_1") is None


def test_an_applied_write_IS_visible_to_the_mirror_overlay(log):
    _apply(log, "Account", "acc_1", {"balance": 900})

    # A sync timestamp from before the write.
    changes = log.get_applied_changes_since("Account", "acc_1", "2000-01-01T00:00:00+00:00")

    assert changes == {"balance": 900}


def test_a_write_older_than_the_last_sync_is_not_overlaid(log):
    # THE bounding property: once the mirror has caught up, the overlay
    # must stop returning that write -- otherwise it grows without
    # limit and eventually shadows the mirror entirely.
    _apply(log, "Account", "acc_1", {"balance": 900})

    assert log.get_applied_changes_since("Account", "acc_1", "2099-01-01T00:00:00+00:00") is None


def test_no_mirror_means_no_overlay_at_all(log):
    # A live deployment passes None -- the live adapter already reads
    # the real, current value, so overlaying anything would be wrong.
    _apply(log, "Account", "acc_1", {"balance": 900})

    assert log.get_applied_changes_since("Account", "acc_1", None) is None


def test_the_most_recent_applied_write_wins(log):
    # Two real writes to the same object -- a reader must see the
    # latest, not whichever the query happened to return first.
    _apply(log, "Account", "acc_1", {"balance": 700})
    _apply(log, "Account", "acc_1", {"balance": 900})

    changes = log.get_applied_changes_since("Account", "acc_1", "2000-01-01T00:00:00+00:00")

    assert changes == {"balance": 900}


def test_the_overlay_is_per_object(log):
    _apply(log, "Account", "acc_1", {"balance": 900})

    assert log.get_applied_changes_since("Account", "acc_2", "2000-01-01T00:00:00+00:00") is None


def test_the_overlay_is_per_object_type(log):
    # Same id, different type -- must not collide.
    _apply(log, "Account", "shared_id", {"balance": 900})

    assert log.get_applied_changes_since("Customer", "shared_id", "2000-01-01T00:00:00+00:00") is None


def test_get_all_applied_changes_since_lists_every_affected_object(log):
    _apply(log, "Account", "acc_1", {"balance": 900})
    _apply(log, "Account", "acc_2", {"balance": 600})

    entries = log.get_all_applied_changes_since("2000-01-01T00:00:00+00:00")

    by_id = {e["object_id"]: e["changes"] for e in entries}
    assert by_id == {"acc_1": {"balance": 900}, "acc_2": {"balance": 600}}


def test_get_all_applied_changes_since_merges_repeated_writes_to_one_object(log):
    # Two writes touching DIFFERENT fields of the same object must
    # merge, not have one silently replace the other wholesale.
    _apply(log, "Account", "acc_1", {"balance": 900})
    _apply(log, "Account", "acc_1", {"currency": "EUR"})

    entries = log.get_all_applied_changes_since("2000-01-01T00:00:00+00:00")

    assert len(entries) == 1
    assert entries[0]["changes"] == {"balance": 900, "currency": "EUR"}


def test_get_all_applied_changes_since_is_empty_with_no_mirror(log):
    _apply(log, "Account", "acc_1", {"balance": 900})

    assert log.get_all_applied_changes_since(None) == []


def test_a_still_pending_write_is_not_returned_by_the_overlay(log):
    # The overlay is specifically for APPLIED writes. A still-pending
    # one is get_pending_changes()' job -- returning it from both would
    # be redundant at best and conflicting at worst.
    log.log_pending_update("Account", "acc_1", {"balance": 900}, {}, "alice", "desc")

    assert log.get_applied_changes_since("Account", "acc_1", "2000-01-01T00:00:00+00:00") is None
    # ...and the in-flight masking DOES see it, unchanged.
    assert log.get_pending_changes("Account", "acc_1") == {"balance": 900}


def test_crash_recovery_is_unaffected_by_the_overlay(log):
    # get_pending_batches() drives resume-on-startup. An applied write
    # must not appear there, and adding the overlay must not have
    # changed that.
    batch_id = log.log_pending_batch(
        [{"object_type": "Account", "object_id": "acc_1", "operation": "update",
          "changes": {"balance": 900}, "expected_current_values": {}}],
        "alice", "desc",
    )
    assert len(log.get_pending_batches()) == 1

    log.mark_batch_applied(batch_id)
    assert log.get_pending_batches() == []


def test_changes_survive_the_round_trip_as_real_json(log):
    # The overlay returns parsed changes, not a raw JSON string.
    _apply(log, "Account", "acc_1", {"balance": 900, "currency": "USD"})

    changes = log.get_applied_changes_since("Account", "acc_1", "2000-01-01T00:00:00+00:00")

    assert isinstance(changes, dict)
    assert changes == json.loads('{"balance": 900, "currency": "USD"}')
