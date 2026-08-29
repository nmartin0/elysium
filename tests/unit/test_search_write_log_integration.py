"""
Tests for search_object()'s write-log integration -- closes the gap
write_log.py's own module docstring used to name explicitly (search_
object() previously queried the real backend directly, meaning an
object mid-update could be MISSING from a search for its own new,
intended value, or WRONGLY included in a search for the old value it's
about to stop having).

Also covers write_mediator.py's _read_current_state_for_criteria(),
the SAME class of gap for a different read path (submission_criteria
evaluation during propose_action()) -- see that method's own updated
docstring.

TEST_SCHEMA deliberately uses an INTEGER id column (ticket_id INTEGER,
not TEXT) for the reconciliation tests specifically -- proving the
real type-consistency fix directly: a naive set().discard(entry
["object_id"]) would silently fail to remove an existing match, since
write_log always stores object_id as a string ("1") while
adapter.find_ids() would return the native integer (1), and "1" != 1
in Python. Confirmed as a real bug caught during design, not a
hypothetical -- this schema exists specifically to prove the fix,
not just the string-id common case.

alice: region us-west, full grants.
"""

import sqlite3

import pytest

from core.deployment_loader import _build_adapters
from core.intermediate_layer.auth import resolve_user_record
from core.ontology import write_log
from core.ontology.mediator import DataMediator
from core.ontology.write_mediator import WriteMediator

TEST_SCHEMA = {
    "Ticket": {
        "storage": {"silo": "primary", "table": "tickets", "id_column": "ticket_id"},
        "id_field": "ticket_id",
        "security": {"field": "region"},
        "fields": {
            "region": {"type": "data"},
            "status": {"type": "data"},
            "priority": {"type": "data"},
        },
    },
}

TEST_ROLES = {
    "full": {"allowed_actions": [
        "read:Ticket", "read:Ticket.ticket_id", "read:Ticket.status", "read:Ticket.priority",
        "execute:Reopen",
    ]},
}

TEST_ACTION_TYPES = {
    "Reopen": {
        "object_type": "Ticket",
        "operation": "update",
        "parameters": {},
        "submission_criteria": [
            {
                "description": "Ticket must currently be closed to reopen it",
                "check": "current_state", "field": "status", "operator": "equals", "value": "closed",
            },
        ],
        "mutations": [{"set": {"property": "status", "value": "open"}}],
    },
}

TEST_USERS = {
    "alice": {"region": "us-west", "role": "full"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def fixture(tmp_path):
    # INTEGER ticket_id, deliberately -- see module docstring.
    db_path = tmp_path / "primary.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE tickets (ticket_id INTEGER PRIMARY KEY, region TEXT, status TEXT, priority TEXT);
        INSERT INTO tickets VALUES (1, 'us-west', 'open', 'low');
        INSERT INTO tickets VALUES (2, 'us-west', 'closed', 'low');
    """)
    conn.commit()
    conn.close()

    write_log_db_path = tmp_path / "write_log.db"
    adapters = _build_adapters({"primary": {"adapter": "sqlite", "connection": {"path": db_path}}})
    mediator = DataMediator(TEST_SCHEMA, adapters, {"Ticket": "primary"}, TEST_ROLES,
                             write_log_db_path=write_log_db_path)
    write_mediator = WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES, write_log_db_path=write_log_db_path)
    return mediator, write_mediator, write_log_db_path


def test_search_with_no_pending_writes_is_unaffected(fixture):
    mediator, _, _ = fixture
    alice = _record("alice")
    assert mediator.search_object(alice, "Ticket", {"status": "open"}) == [1]
    assert mediator.search_object(alice, "Ticket", {"status": "closed"}) == [2]


def test_search_finds_object_by_its_new_pending_value(fixture):
    # Ticket 1 has a pending write changing status "open" -> "closed",
    # not yet applied to the real backend -- searching for "closed"
    # must find it anyway, matching what get_field() would already show.
    mediator, _, write_log_db_path = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        write_log_db_path, "Ticket", 1, {"status": "closed"}, {"status": "open"}, "alice", "test",
    )

    # Confirmed: the REAL backend still has the old value.
    real_adapter = mediator.adapters["primary"]
    raw = real_adapter.get_raw_field("Ticket", 1, "status", {"storage": {"table": "tickets", "id_column": "ticket_id"}})
    assert raw == "open", "the real backend should not have changed yet"

    result = mediator.search_object(alice, "Ticket", {"status": "closed"})
    # Ticket 2 already, genuinely matches "closed" in the real backend
    # (unrelated to this test) -- ticket 1 must ALSO be present, via
    # its pending write, alongside it.
    assert set(result) == {1, 2}
    # THE type-consistency proof -- ticket 1's id is a real Python int
    # here (from write_log's own string-stored object_id, "1", being
    # correctly resolved to the actual candidate), not a string "1"
    # that would silently break downstream get_field()/check_access()
    # calls expecting the native type.
    assert all(isinstance(candidate_id, int) for candidate_id in result)


def test_search_no_longer_finds_object_by_its_old_pending_value(fixture):
    # THE key correctness property this whole mechanism exists for --
    # and the one that specifically exercises the discard()-vs-integer-
    # id bug caught during design: ticket 1 still matches "open" in the
    # REAL backend (transiently, until the write applies), but must NOT
    # be returned once its pending write says otherwise.
    mediator, _, write_log_db_path = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        write_log_db_path, "Ticket", 1, {"status": "closed"}, {"status": "open"}, "alice", "test",
    )

    result = mediator.search_object(alice, "Ticket", {"status": "open"})
    assert result == [], "ticket 1 must be excluded despite the real backend still matching 'open'"


def test_search_reconciliation_considers_full_criteria_not_just_changed_fields(fixture):
    # Ticket 1's pending write only touches "status" -- "priority" is
    # untouched. A multi-field search must merge the PENDING value for
    # status with the REAL, current value for priority, not just check
    # the field the pending write happens to change.
    mediator, _, write_log_db_path = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        write_log_db_path, "Ticket", 1, {"status": "closed"}, {"status": "open"}, "alice", "test",
    )

    # Matches on BOTH the pending status AND the real, unaffected
    # priority -- ticket 2 ALSO, genuinely matches this (real
    # status='closed', real priority='low'), unrelated to this test.
    assert set(mediator.search_object(alice, "Ticket", {"status": "closed", "priority": "low"})) == {1, 2}
    # Does NOT match if the REAL, unaffected field is wrong, even
    # though the pending field matches -- neither ticket has priority
    # "high" for real.
    assert mediator.search_object(alice, "Ticket", {"status": "closed", "priority": "high"}) == []


def test_search_reconciliation_respects_rbac(fixture):
    # A newly-discovered match (via a pending write) must still go
    # through the SAME check_access() filter as any other candidate --
    # it doesn't bypass RBAC/MAC just because it was found via the log.
    mediator, _, write_log_db_path = fixture
    wrong_region_users = {"bob": {"region": "us-east", "role": "full"}}
    bob = resolve_user_record(wrong_region_users, "bob", "region")

    write_log.log_pending_update(
        write_log_db_path, "Ticket", 1, {"status": "closed"}, {"status": "open"}, "alice", "test",
    )

    assert mediator.search_object(bob, "Ticket", {"status": "closed"}) == []


def test_search_ignores_pending_entries_for_a_different_object_type(fixture):
    mediator, _, write_log_db_path = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        write_log_db_path, "SomeOtherType", 1, {"status": "closed"}, {"status": "open"}, "alice", "test",
    )

    # Ticket 1's real status is genuinely "open" -- the OTHER type's
    # pending entry (same numeric id, different type) must not leak in.
    assert mediator.search_object(alice, "Ticket", {"status": "open"}) == [1]
    # Ticket 2 is already, genuinely "closed" for real -- unaffected by
    # the unrelated SomeOtherType entry either way.
    assert mediator.search_object(alice, "Ticket", {"status": "closed"}) == [2]


def test_search_ignores_pending_entries_that_dont_touch_criteria_fields(fixture):
    # Ticket 1 has a pending write touching ONLY "priority" -- a search
    # on "status" alone has nothing to reconcile against it at all.
    mediator, _, write_log_db_path = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        write_log_db_path, "Ticket", 1, {"priority": "high"}, {"priority": "low"}, "alice", "test",
    )

    assert mediator.search_object(alice, "Ticket", {"status": "open"}) == [1]


def test_submission_criteria_sees_pending_value_not_stale_backend_state(fixture, isolated_audit_log):
    # _read_current_state_for_criteria()'s own fix -- ticket 2 starts
    # "closed" for real, but has a pending write (not yet applied)
    # setting it to "open". A NEW propose_action() evaluating "must
    # currently be closed" must see the PENDING "open" value and
    # correctly REJECT the reopen attempt, not the stale, real "closed"
    # that would incorrectly allow it.
    mediator, write_mediator, write_log_db_path = fixture
    alice = _record("alice")

    write_log.log_pending_update(
        write_log_db_path, "Ticket", 2, {"status": "open"}, {"status": "closed"}, "alice",
        "simulated in-flight update to ticket 2",
    )

    from core.ontology.submission_criteria import SubmissionCriteriaViolation
    with pytest.raises(SubmissionCriteriaViolation, match="must currently be closed"):
        write_mediator.propose_action(alice, "Reopen", 2, {})
