"""
Tests for multi-storage create -- see write_log.py's own module
docstring for the full mechanism this proves: the object's own id must
be supplied EXPLICITLY (never auto-generated, matching Palantir
Foundry's own MDO requirement that a primary key already exist,
matching, in every backing datasource), logged first via
write_log.log_pending_create(), then applied to each storage group
sequentially via WriteMediator._apply_create_via_log(), with the id
injected into every group's own fields, not just whichever one
group's mutations happened to place it in naturally.

Reuses test_mdo.py's own MDO Customer schema/fixture shape
deliberately, for the same reason that file does: risk_db's own
id_column (cust_ref, not customer_id) and column name (score_val, not
risk_score) are real mismatches worth exercising throughout, not just
"two storages, same naming convention" -- this specifically proves the
id-injection logic correctly translates the shared id_field name to
EACH storage's own, differently-named id column.

alice: region us-west, full grants across both storages.
"""

import sqlite3

import pytest

from core.deployment_loader import _build_adapters
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLog
from core.ontology.write_mediator import WriteMediator

TEST_SCHEMA = {
    "Customer": {
        "storage": {"silo": "primary_sql", "table": "customers", "id_column": "customer_id"},
        "additional_storage": {
            "risk_db": {"silo": "risk_sql", "table": "customer_risk", "id_column": "cust_ref"},
        },
        "id_field": "customer_id",
        "security": {"field": "region"},
        "fields": {
            "region": {"type": "data"},
            "name": {"type": "data"},
            "risk_score": {"type": "data", "storage": "risk_db", "column": "score_val"},
        },
    },
}

TEST_ROLES = {
    "full": {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name", "read:Customer.risk_score",
        "execute:CreateCustomerFull", "execute:CreateCustomerNameOnly", "execute:CreateCustomerNameOnlyNoId",
    ]},
}

TEST_ACTION_TYPES = {
    # Multi-storage: name (primary) + risk_score (risk_db), WITH an
    # explicit customer_id -- the case this whole increment exists to
    # make possible. region via user.security_value, matching this
    # project's own established create pattern -- omitting it would
    # leave the new row's own MAC field unset, denying every reader
    # (including the very user who just created it).
    "CreateCustomerFull": {
        "affected_object_types": ["Customer"],
        "parameters": {
            "new_id": {"type": "object_reference", "object_type": "Customer", "required": True},
            "new_name": {"type": "string", "required": True},
            "new_score": {"type": "number", "required": True},
        },
        "sub_writes": [{
            "object_type": "Customer",
            "object_id": "parameter.new_id",
            "operation": "create",
            "mutations": [
                {"set": {"property": "customer_id", "value": "parameter.new_id"}},
                {"set": {"property": "region", "value": "user.security_value"}},
                {"set": {"property": "name", "value": "parameter.new_name"}},
                {"set": {"property": "risk_score", "value": "parameter.new_score"}},
            ],
        }],
    },
    # Single-storage: name only (plus id + region) -- proves this
    # path is now unified with the multi-storage one, both going
    # through the SAME log-based mechanism.
    "CreateCustomerNameOnly": {
        "affected_object_types": ["Customer"],
        "parameters": {
            "new_id": {"type": "object_reference", "object_type": "Customer", "required": True},
            "new_name": {"type": "string", "required": True},
        },
        "sub_writes": [{
            "object_type": "Customer",
            "object_id": "parameter.new_id",
            "operation": "create",
            "mutations": [
                {"set": {"property": "customer_id", "value": "parameter.new_id"}},
                {"set": {"property": "region", "value": "user.security_value"}},
                {"set": {"property": "name", "value": "parameter.new_name"}},
            ],
        }],
    },
    # DELIBERATELY omits customer_id from its own mutations -- for
    # test_single_storage_create_still_requires_an_explicit_id, proving
    # the explicit-id requirement is now universal, not just for create
    # spanning multiple storages. new_id is still a REQUIRED
    # object_reference parameter (every sub_write needs its own
    # resolved object_id regardless of operation -- see SubWrite's own
    # docstring), but it is deliberately never referenced by any
    # mutation below -- exactly the gap this test exists to prove is
    # still caught.
    "CreateCustomerNameOnlyNoId": {
        "affected_object_types": ["Customer"],
        "parameters": {
            "new_id": {"type": "object_reference", "object_type": "Customer", "required": True},
            "new_name": {"type": "string", "required": True},
        },
        "sub_writes": [{
            "object_type": "Customer",
            "object_id": "parameter.new_id",
            "operation": "create",
            "mutations": [
                {"set": {"property": "region", "value": "user.security_value"}},
                {"set": {"property": "name", "value": "parameter.new_name"}},
            ],
        }],
    },
}

TEST_USERS = {
    "alice": {"region": "us-west", "role": "full"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def fixture(tmp_path, isolated_audit_log):
    db_primary = tmp_path / "primary.db"
    conn = sqlite3.connect(db_primary)
    conn.executescript("""
        CREATE TABLE customers (customer_id TEXT PRIMARY KEY, region TEXT, name TEXT);
    """)
    conn.commit()
    conn.close()

    db_risk = tmp_path / "risk.db"
    conn = sqlite3.connect(db_risk)
    conn.executescript("""
        CREATE TABLE customer_risk (cust_ref TEXT PRIMARY KEY, score_val REAL);
    """)
    conn.commit()
    conn.close()

    write_log = WriteLog(tmp_path / "write_log.db")
    audit_log = AuditLog(isolated_audit_log / "audit.log")

    adapters = _build_adapters({
        "primary_sql": {"adapter": "sqlite", "connection": {"path": db_primary}},
        "risk_sql": {"adapter": "sqlite", "connection": {"path": db_risk}},
    })
    mediator = DataMediator(TEST_SCHEMA, adapters, {"Customer": "primary_sql"}, TEST_ROLES,
                             write_log=write_log, audit_log=audit_log)
    write_mediator = WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES)
    return mediator, write_mediator, write_log


def _direct_write(mediator, silo, table, columns: dict):
    # Bypasses the write log ENTIRELY -- simulates "this group's
    # create already committed to the real backend before the crash."
    # Takes the group's FULL column set, not just one arbitrary field
    # -- a real create_object() call for a storage group always
    # inserts every field that group owns together, in one INSERT
    # (region alongside customer_id and name for the primary group
    # here); a partial simulation would leave a row resume correctly
    # judges as "already exists" but that never had a real MAC field
    # set at all, an artifact of the test, not of resume itself.
    adapter = mediator.adapters[silo]
    column_names = ", ".join(columns.keys())
    placeholders = ", ".join("?" for _ in columns)
    with adapter._connection() as conn:
        conn.execute(f"INSERT INTO {table} ({column_names}) VALUES ({placeholders})", tuple(columns.values()))
        conn.commit()


def test_single_storage_create_still_requires_an_explicit_id(fixture):
    # Genuinely NEW behavior -- single-storage create used to allow
    # auto-generated ids (the pre-this-session default). Now unified
    # with the multi-storage case: EVERY create requires an explicit
    # id, regardless of storage count -- see WriteMediator.
    # propose_action()'s own comment on why this was worth unifying
    # rather than keeping as two separately-maintained mechanisms.
    _, write_mediator, _ = fixture
    alice = _record("alice")

    with pytest.raises(ValueError, match="requires an explicit 'customer_id' value"):
        write_mediator.propose_action(alice, "CreateCustomerNameOnlyNoId",
                                       {"new_id": "cust_ignored", "new_name": "Solo Customer"})


def test_single_storage_create_also_goes_through_the_log(fixture):
    # THE unification itself, proven directly: single-storage create
    # is no longer a separate, log-free path -- it's the SAME
    # _apply_create_via_log() multi-storage create uses, just with a
    # single-element group list (the degenerate case, same as
    # _apply_update_via_log() already handled for update). By the time
    # confirm_and_execute() returns, the entry is already resolved
    # (logged, applied, marked applied, all within the same call) --
    # so "no pending entries left" is expected either way; what this
    # test actually proves is that the create still succeeds cleanly
    # through the SHARED mechanism, not that the log was bypassed.
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    pending = write_mediator.propose_action(
        alice, "CreateCustomerNameOnly", {"new_id": "cust_solo", "new_name": "Solo Customer"}
    )
    result = write_mediator.confirm_and_execute(pending, approved=True)

    new_id = result["object_id"]
    assert new_id == "cust_solo"
    assert mediator.get_field(alice, "Customer", new_id, "name") == "Solo Customer"
    assert write_log.get_pending_entries() == []


def test_apply_create_via_log_logs_under_the_real_id_not_none(fixture, monkeypatch):
    # A REAL bug caught during design, not hypothetical: pending.
    # object_id is ALWAYS None for a "create" action (the caller
    # doesn't know the id yet when proposing one -- that's the whole
    # point of create). Using it directly for the write_log row's own
    # object_id (instead of the real id from pending.changes) would
    # store that row under object_id="None" -- breaking
    # get_pending_changes()'s own by-id lookup for the REAL id during
    # the brief window before mark_applied() runs, and breaking
    # resume_pending_writes() outright if a crash happened in that
    # exact window. Every other test in this file bypasses
    # propose_action()/confirm_and_execute() entirely for its "crashed"
    # scenarios (constructing the log entry directly, already under the
    # correct id), so none of them would have caught this -- this test
    # goes through the REAL path specifically to close that gap,
    # intercepting create_object() to inspect the log's own state
    # WHILE still mid-apply (lock held, mark_applied() not yet called).
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    pending = write_mediator.propose_action(
        alice, "CreateCustomerFull",
        {"new_id": "cust_mid_apply", "new_name": "Mid Apply", "new_score": 0.3},
    )

    original_create_object = mediator.adapters["primary_sql"].create_object
    observed = {}

    def spy_create_object(*args, **kwargs):
        observed["pending_changes"] = write_log.get_pending_changes("Customer", "cust_mid_apply")
        return original_create_object(*args, **kwargs)

    monkeypatch.setattr(mediator.adapters["primary_sql"], "create_object", spy_create_object)
    write_mediator.confirm_and_execute(pending, approved=True)

    assert observed["pending_changes"] is not None, \
        "the log entry must be findable under the REAL id while still mid-apply"
    assert observed["pending_changes"]["name"] == "Mid Apply"


def test_multi_storage_create_applies_to_every_storage(fixture):
    # THE positive case -- an explicit id makes multi-storage create
    # possible at all. Both storages end up with a row under the SAME
    # id, despite their genuinely different id column names
    # (customer_id vs cust_ref).
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    pending = write_mediator.propose_action(
        alice, "CreateCustomerFull",
        {"new_id": "cust_001", "new_name": "Ada Okafor", "new_score": 0.42},
    )
    result = write_mediator.confirm_and_execute(pending, approved=True)
    assert result == {"status": "written", "object_id": "cust_001"}

    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "Ada Okafor"
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.42

    # Proven directly against the real backend, not just through the
    # log's own read-merge masking -- the row genuinely exists in BOTH
    # storages, under each one's own id column name.
    primary_adapter = mediator.adapters["primary_sql"]
    raw_name = primary_adapter.get_raw_field("Customer", "cust_001", "name",
                                              {"storage": {"table": "customers", "id_column": "customer_id"}})
    assert raw_name == "Ada Okafor"
    risk_adapter = mediator.adapters["risk_sql"]
    raw_score = risk_adapter.get_raw_field("Customer", "cust_001", "score_val",
                                            {"storage": {"table": "customer_risk", "id_column": "cust_ref"}})
    assert raw_score == 0.42

    # The log entry is genuinely resolved, not left pending.
    assert write_log.get_pending_entries() == []


def test_resume_completes_a_create_that_never_applied(fixture):
    # Simulates the cleanest crash: the log entry was written, but the
    # process died before EITHER storage group's create_object() call
    # ever ran -- neither storage has the row at all yet.
    mediator, write_mediator, write_log = fixture
    alice = _record("alice")

    write_log.log_pending_create(
        "Customer", "cust_001",
        {"customer_id": "cust_001", "region": "us-west", "name": "New Customer", "risk_score": 0.55},
        "alice", "simulated crash before any group applied",
    )

    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 1, "already_applied": 0, "ambiguous": 0}

    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "New Customer"
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.55
    assert write_log.get_pending_entries() == []


def test_resume_skips_already_created_group_and_completes_the_other(fixture):
    # THE key correctness property -- see _resume_one_create_entry()'s
    # own docstring. Simulates "crashed AFTER the primary-storage
    # group's INSERT committed, BEFORE the MDO group's did": the
    # primary row already exists for real; risk_db's row doesn't yet.
    # A naive resume that just re-ran create_object() for BOTH groups
    # would hit a real PRIMARY KEY constraint violation trying to
    # re-insert the already-existing primary row.
    mediator, write_mediator, write_log = fixture

    write_log.log_pending_create(
        "Customer", "cust_001",
        {"customer_id": "cust_001", "region": "us-west", "name": "New Customer", "risk_score": 0.55},
        "alice", "simulated crash after primary group applied, before MDO group",
    )
    _direct_write(mediator, "primary_sql", "customers",
                  {"customer_id": "cust_001", "region": "us-west", "name": "New Customer"})

    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 1, "already_applied": 0, "ambiguous": 0}

    alice = _record("alice")
    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "New Customer"
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.55
    assert write_log.get_pending_entries() == []


def test_resume_when_every_group_already_created(fixture):
    # The OTHER clean case: the crash happened AFTER every group's
    # create already committed, but BEFORE mark_applied() ran. Resume
    # should recognize this and simply close the entry out -- no group
    # gets a redundant, constraint-violating create_object() call.
    mediator, write_mediator, write_log = fixture

    write_log.log_pending_create(
        "Customer", "cust_001",
        {"customer_id": "cust_001", "region": "us-west", "name": "New Customer", "risk_score": 0.55},
        "alice", "simulated crash after both groups applied, before mark_applied",
    )
    _direct_write(mediator, "primary_sql", "customers",
                  {"customer_id": "cust_001", "region": "us-west", "name": "New Customer"})
    _direct_write(mediator, "risk_sql", "customer_risk", {"cust_ref": "cust_001", "score_val": 0.55})

    summary = write_mediator.resume_pending_writes()
    assert summary == {"resumed": 0, "already_applied": 1, "ambiguous": 0}
    assert write_log.get_pending_entries() == []


def test_resume_create_is_idempotent(fixture):
    mediator, write_mediator, write_log = fixture

    write_log.log_pending_create(
        "Customer", "cust_001",
        {"customer_id": "cust_001", "region": "us-west", "name": "New Customer", "risk_score": 0.55},
        "alice", "test",
    )

    first = write_mediator.resume_pending_writes()
    assert first == {"resumed": 1, "already_applied": 0, "ambiguous": 0}

    second = write_mediator.resume_pending_writes()
    assert second == {"resumed": 0, "already_applied": 0, "ambiguous": 0}


def test_get_field_sees_pending_create_value(fixture):
    # get_field() itself needed NO changes for create at all -- it's
    # already operation-agnostic (just checks "is this field in the
    # log's own pending changes dict"). Proven explicitly here, not
    # just assumed from that reasoning.
    mediator, _, write_log = fixture
    alice = _record("alice")

    write_log.log_pending_create(
        "Customer", "cust_001",
        {"customer_id": "cust_001", "region": "us-west", "name": "New Customer", "risk_score": 0.55},
        "alice", "test",
    )

    # Neither storage has the row yet -- get_field() must still report
    # the intended, pending value via the log's own read-merge.
    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "New Customer"
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.55


def test_search_finds_object_by_its_pending_create(fixture, isolated_audit_log):
    # THE "sticky note" fix's whole reason for existing. Neither
    # storage has cust_001's row yet -- a search scoped to risk_db's
    # own field (risk_score) would, without the fix, try to read the
    # id back off a row that doesn't exist in risk_db at all, getting
    # None instead of the real id.
    mediator, _, write_log = fixture
    alice = _record("alice")

    write_log.log_pending_create(
        "Customer", "cust_001",
        {"customer_id": "cust_001", "region": "us-west", "name": "New Customer", "risk_score": 0.55},
        "alice", "test",
    )

    result = mediator.search_object(alice, "Customer", {"risk_score": 0.55})
    assert result == ["cust_001"]
    # Never a None or a bare, unresolved string standing in for the id.
    assert result[0] is not None


def test_search_finds_object_by_its_pending_create_on_primary_field_too(fixture):
    # Same fix, exercised via the PRIMARY storage's own field instead
    # -- confirms the sticky-note path works regardless of which
    # storage the search happens to be scoped to, not just the MDO one.
    mediator, _, write_log = fixture
    alice = _record("alice")

    write_log.log_pending_create(
        "Customer", "cust_001",
        {"customer_id": "cust_001", "region": "us-west", "name": "New Customer", "risk_score": 0.55},
        "alice", "test",
    )

    assert mediator.search_object(alice, "Customer", {"name": "New Customer"}) == ["cust_001"]
