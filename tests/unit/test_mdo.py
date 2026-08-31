"""
Tests for multi-datasource object types (MDO) -- one object type whose
DIFFERENT properties are backed by genuinely different silos, joined
on a shared identity value. Matches Palantir Foundry's own column-wise
MDO concept (see core/ontology/mediator.py's _resolve_shared_storage()
docstring for the full architectural reasoning and this project's
deliberate v1 scope boundary).

TEST_SCHEMA deliberately exercises the two real-world mismatches MDO
exists to handle, not just "two silos, same naming convention":
  - risk_db's OWN id_column is "cust_ref", not "customer_id" -- MDO
    assumes the IDENTITY VALUE is shared across silos, never that the
    ID COLUMN NAME is.
  - risk_score's OWN column in risk_db is "score_val", not
    "risk_score" -- the column-name override (get_field_column()),
    folded into this same schema surface since a real external silo
    won't always happen to name its columns like our own field names.

alice: region us-west, full grants including BOTH storages
dave: region us-west, grants Customer.name but NOT Customer.risk_score
      -- for the field-level-RBAC-still-applies-per-MDO-field test
"""

import sqlite3

import pytest

from core.deployment_loader import _build_adapters
from core.intermediate_layer.audit import AuditLog
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from core.ontology.write_log import WriteLog
from core.ontology.write_mediator import WriteMediator
from tests.conftest import read_audit_log

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
            # A FORWARD LINK, also MDO-backed (cardinality: one -- a
            # real column, not a computed reverse relationship). Never
            # actually exercised before -- get_field()'s MDO resolution
            # path is SHARED between plain data fields and forward
            # links, but "the code path is shared" isn't the same as
            # "proven to work for a link specifically."
            "preferred_agent_id": {
                "type": "link", "target": "Agent", "cardinality": "one",
                "storage": "risk_db", "column": "agent_ref",
            },
        },
    },
}

TEST_ROLES = {
    "full": {"allowed_actions": [
        "read:Customer", "read:Customer.customer_id", "read:Customer.name", "read:Customer.risk_score",
        "read:Customer.preferred_agent_id",
        "execute:UpdateRiskScore", "execute:CreateCustomerWithNameAndRiskScore", "execute:CreateCustomerRiskOnly",
    ]},
    "name_only": {"allowed_actions": ["read:Customer", "read:Customer.customer_id", "read:Customer.name"]},
}

TEST_ACTION_TYPES = {
    "UpdateRiskScore": {
        "affected_object_types": ["Customer"],
        "parameters": {
            "customer_id": {"type": "object_reference", "object_type": "Customer", "required": True},
            "new_score": {"type": "number", "required": True},
        },
        "sub_writes": [{
            "object_type": "Customer",
            "object_id": "parameter.customer_id",
            "operation": "update",
            "mutations": [{"set": {"property": "risk_score", "value": "parameter.new_score"}}],
        }],
    },
    # DELIBERATELY mixes a primary-storage field (name) and an MDO
    # field (risk_score) in ONE action's mutations, WITHOUT ever naming
    # customer_id -- for
    # test_multi_storage_create_without_explicit_id_is_rejected.
    # Multi-storage create IS now solved (see
    # core/ontology/write_log.py's own module docstring), but requires
    # the object's own id explicitly among the mutations; this action
    # deliberately omits it to prove that requirement is still enforced.
    # new_id is still a REQUIRED object_reference parameter -- every
    # sub_write needs its own resolved object_id regardless of
    # operation (see SubWrite's own docstring) -- but it is
    # DELIBERATELY never referenced by any mutation below, which is
    # exactly the gap this test exists to prove is still caught.
    "CreateCustomerWithNameAndRiskScore": {
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
                {"set": {"property": "name", "value": "parameter.new_name"}},
                {"set": {"property": "risk_score", "value": "parameter.new_score"}},
            ],
        }],
    },
    # DELIBERATELY sets an explicit id (now required for every create --
    # see WriteMediator.propose_action()'s own comment on why) and
    # risk_score, but never "name" or "region" -- for
    # test_create_without_setting_security_field_produces_an_unreadable_row
    # below. Once every create requires an explicit id, this can no
    # longer produce a genuinely ORPHANED, primary-row-less insert the
    # way it used to (id_field always resolves to primary storage, so
    # a primary row now always exists) -- but the row it DOES produce
    # is still incomplete (region left NULL), and still unreadable for
    # the same underlying reason, just via a real row with a missing
    # field rather than a missing row entirely.
    "CreateCustomerRiskOnly": {
        "affected_object_types": ["Customer"],
        "parameters": {
            "new_id": {"type": "object_reference", "object_type": "Customer", "required": True},
            "risk_score": {"type": "number", "required": True},
        },
        "sub_writes": [{
            "object_type": "Customer",
            "object_id": "parameter.new_id",
            "operation": "create",
            "mutations": [
                {"set": {"property": "customer_id", "value": "parameter.new_id"}},
                {"set": {"property": "risk_score", "value": "parameter.risk_score"}},
            ],
        }],
    },
}

TEST_USERS = {
    "alice": {"region": "us-west", "role": "full"},
    "dave": {"region": "us-west", "role": "name_only"},
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "region")


@pytest.fixture
def mediator(tmp_path, isolated_audit_log):
    db_primary = tmp_path / "primary.db"
    conn = sqlite3.connect(db_primary)
    conn.executescript("""
        CREATE TABLE customers (customer_id TEXT PRIMARY KEY, region TEXT, name TEXT);
        INSERT INTO customers VALUES ('cust_001', 'us-west', 'Ada Okafor');
        INSERT INTO customers VALUES ('cust_002', 'us-west', 'Ben Carter');
    """)
    conn.commit()
    conn.close()

    db_risk = tmp_path / "risk.db"
    conn = sqlite3.connect(db_risk)
    conn.executescript("""
        CREATE TABLE customer_risk (cust_ref TEXT PRIMARY KEY, score_val REAL, agent_ref TEXT);
        INSERT INTO customer_risk VALUES ('cust_001', 0.42, 'agent_007');
    """)
    conn.commit()
    conn.close()

    adapters = _build_adapters({
        "primary_sql": {"adapter": "sqlite", "connection": {"path": db_primary}},
        "risk_sql": {"adapter": "sqlite", "connection": {"path": db_risk}},
    })
    silo_for_type = {"Customer": "primary_sql"}
    return DataMediator(TEST_SCHEMA, adapters, silo_for_type, TEST_ROLES,
                         write_log=WriteLog(tmp_path / "write_log.db"),
                         audit_log=AuditLog(isolated_audit_log / "audit.log"))


def test_reads_a_primary_storage_field_normally(mediator):
    assert mediator.get_field(_record("alice"), "Customer", "cust_001", "name") == "Ada Okafor"


def test_reads_an_mdo_field_from_a_genuinely_different_silo(mediator):
    # Different silo, different id_column name (cust_ref vs
    # customer_id), different column name (score_val vs risk_score) --
    # all three mismatches resolved correctly in one call.
    assert mediator.get_field(_record("alice"), "Customer", "cust_001", "risk_score") == 0.42


def test_field_level_rbac_still_applies_independently_per_mdo_field(mediator):
    # dave can see name (primary storage) but NOT risk_score (MDO,
    # risk_db) -- MDO doesn't create a new security concept; the
    # existing per-field RBAC gate just needs to keep working correctly
    # once fields can come from different places.
    dave = _record("dave")
    assert mediator.get_field(dave, "Customer", "cust_001", "name") == "Ada Okafor"
    assert mediator.get_field(dave, "Customer", "cust_001", "risk_score") is None


def test_search_by_a_primary_field_still_works(mediator):
    assert mediator.search_object(_record("alice"), "Customer", {"name": "Ada Okafor"}) == ["cust_001"]


def test_search_by_an_mdo_field_resolves_to_the_right_silo(mediator):
    assert mediator.search_object(_record("alice"), "Customer", {"risk_score": 0.42}) == ["cust_001"]


def test_search_mixing_fields_from_different_storages_is_rejected(mediator):
    # THE v1 scope boundary for reads -- a single search filter may
    # only touch ONE storage at a time. Federated intersection across
    # storages is real, unsolved territory, deliberately out of scope.
    with pytest.raises(ValueError, match="cannot combine fields from multiple storages"):
        mediator.search_object(_record("alice"), "Customer", {"name": "Ada Okafor", "risk_score": 0.42})


def test_action_to_an_mdo_field_actually_changes_the_right_database(mediator):
    write_mediator = WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES)
    alice = _record("alice")

    pending = write_mediator.propose_action(alice, "UpdateRiskScore", {"customer_id": "cust_001", "new_score": 0.99})
    assert pending.sub_writes[0].expected_current_values == {"risk_score": 0.42}

    outcome = write_mediator.confirm_and_execute(pending, approved=True)
    assert outcome == {"status": "written", "object_ids": ["cust_001"]}
    assert mediator.get_field(alice, "Customer", "cust_001", "risk_score") == 0.99

    # And the PRIMARY storage's own field is provably untouched --
    # proof the write genuinely only reached risk_db, not primary_sql.
    assert mediator.get_field(alice, "Customer", "cust_001", "name") == "Ada Okafor"


def test_create_without_explicit_id_is_rejected(mediator):
    # An explicit id is REQUIRED for EVERY create now, not just one
    # spanning multiple storages -- see WriteMediator.propose_action()'s
    # own comment on why this was unified rather than kept as two
    # separately-maintained mechanisms (matches "update"'s own
    # precedent of a single, unconditional path regardless of storage
    # count). Also matches Palantir Foundry's own MDO requirement that
    # a primary key already exist, matching, in every backing
    # datasource, never auto-generated by one storage and propagated
    # to the others. Proven here via a named "create" action whose OWN
    # declared mutations mix a primary field (name) and an MDO field
    # (risk_score) without ever naming customer_id itself -- the
    # multi-storage case still exercises this same, now-universal rule.
    write_mediator = WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES)
    alice = _record("alice")
    with pytest.raises(ValueError, match="requires an explicit 'customer_id' value"):
        write_mediator.propose_action(alice, "CreateCustomerWithNameAndRiskScore",
                                       {"new_id": "cust_998", "new_name": "New Name", "new_score": 0.5})


def test_search_with_empty_criteria_defaults_to_primary_storage(mediator):
    # No fields specified at all -- "give me everything" -- must not
    # crash trying to resolve a shared storage across zero fields; the
    # primary storage is the only sensible default. Set comparison,
    # not list equality -- SQLite doesn't guarantee row order without
    # an explicit ORDER BY, and this fixture now has two customers
    # (cust_002 added specifically so the missing-row-on-the-MDO-side
    # test below can exercise a REAL existing primary customer, not a
    # completely nonexistent one).
    result = mediator.search_object(_record("alice"), "Customer", {})
    assert set(result) == {"cust_001", "cust_002"}


def test_reads_an_mdo_backed_forward_link_field(mediator):
    # get_field()'s MDO resolution path is SHARED between plain data
    # fields and forward links (cardinality: one) -- never actually
    # exercised with a link before this test. Returns the raw
    # reference value (an opaque "Agent" id here) -- link resolution
    # itself doesn't care whether the field holding it is MDO-backed
    # or not, same as a plain data field.
    assert mediator.get_field(_record("alice"), "Customer", "cust_001", "preferred_agent_id") == "agent_007"


def test_search_mixing_id_field_with_an_mdo_field_is_rejected(mediator):
    # id_field gets its OWN special-case branch in
    # _resolve_shared_storage() (always resolves to the primary
    # storage, never additional_storage) -- a genuinely different code
    # path than two regular fields being mixed, so it earns its own
    # dedicated test rather than assuming the general case covers it.
    with pytest.raises(ValueError, match="cannot combine fields from multiple storages"):
        mediator.search_object(_record("alice"), "Customer", {"customer_id": "cust_001", "risk_score": 0.42})


def test_missing_row_on_the_mdo_side_returns_none_not_a_crash(mediator, isolated_audit_log):
    # A REAL, GENUINELY EXISTING primary customer (cust_002) that has
    # no corresponding row in risk_db at all (e.g. never risk-scored
    # yet) -- must behave like any other missing value in this system
    # (None), not raise. Matches get_field()'s existing "doesn't
    # exist" semantics, just exercised for the MDO side specifically.
    #
    # DELIBERATELY uses cust_002, not a made-up id -- an earlier
    # version of this test used a completely nonexistent customer_id,
    # which meant check_access() itself denied via MAC (the row
    # genuinely doesn't exist in the PRIMARY table either) BEFORE ever
    # reaching the MDO resolution code this test claims to exercise.
    # That version passed for the wrong reason -- it never actually
    # tested the MDO-side missing-row path at all. Confirmed directly:
    # a fresh, real access_check entry with mac_allowed=True below
    # proves the request genuinely reached MDO resolution this time,
    # not an earlier MAC denial standing in for it.
    result = mediator.get_field(_record("alice"), "Customer", "cust_002", "risk_score")
    assert result is None

    entries = read_audit_log(isolated_audit_log)
    access_check_entries = [e for e in entries if e["stage"] == "access_check"]
    assert access_check_entries[0]["mac_allowed"] is True
    assert access_check_entries[0]["rbac_allowed"] is True
    # And genuinely NOT a security-resolution failure -- cust_002's
    # region resolves just fine from the PRIMARY table; it's only the
    # risk_db side that's missing a row.
    assert not any(e["stage"] == "security_resolution_failed" for e in entries)


def test_security_field_that_is_itself_mdo_backed(tmp_path, isolated_audit_log):
    # A REAL BUG this test guards against: _get_security_value() used
    # to bypass MDO resolution entirely, always querying the type's
    # PRIMARY adapter/table regardless of where security["field"]
    # actually lived -- raising a raw sqlite3.OperationalError ("no
    # such column") the moment the security-bearing field was itself
    # MDO-backed. Confirmed as a real, reproducible crash before being
    # fixed, not just a theoretical concern -- see
    # core/ontology/mediator.py's _get_security_value() docstring.
    #
    # A dedicated schema/fixture, not the shared one above -- this
    # needs "region" (the type's own MAC boundary) to be MDO-backed,
    # which the shared TEST_SCHEMA deliberately does NOT do (region
    # stays on primary_sql there, matching the realistic, common case).
    schema = {
        "Customer": {
            "storage": {"silo": "primary_sql", "table": "customers", "id_column": "customer_id"},
            "additional_storage": {
                "risk_db": {"silo": "risk_sql", "table": "customer_risk", "id_column": "cust_ref"},
            },
            "id_field": "customer_id",
            "security": {"field": "region"},
            "fields": {
                "region": {"type": "data", "storage": "risk_db", "column": "region_val"},
                "name": {"type": "data"},
            },
        },
    }
    roles = {"r": {"allowed_actions": ["read:Customer", "read:Customer.customer_id", "read:Customer.name"]}}

    db_primary = tmp_path / "primary2.db"
    conn = sqlite3.connect(db_primary)
    conn.executescript("""
        CREATE TABLE customers (customer_id TEXT PRIMARY KEY, name TEXT);
        INSERT INTO customers VALUES ('cust_001', 'Ada Okafor');
    """)
    conn.commit()
    conn.close()

    db_risk = tmp_path / "risk2.db"
    conn = sqlite3.connect(db_risk)
    conn.executescript("""
        CREATE TABLE customer_risk (cust_ref TEXT PRIMARY KEY, region_val TEXT);
        INSERT INTO customer_risk VALUES ('cust_001', 'us-west');
    """)
    conn.commit()
    conn.close()

    adapters = _build_adapters({
        "primary_sql": {"adapter": "sqlite", "connection": {"path": db_primary}},
        "risk_sql": {"adapter": "sqlite", "connection": {"path": db_risk}},
    })
    mediator = DataMediator(schema, adapters, {"Customer": "primary_sql"}, roles,
                             audit_log=AuditLog(isolated_audit_log / "audit.log"))

    matching_region = resolve_user_record({"alice": {"region": "us-west", "role": "r"}}, "alice", "region")
    wrong_region = resolve_user_record({"bob": {"region": "us-east", "role": "r"}}, "bob", "region")

    # Must resolve correctly, in BOTH directions -- allow when the
    # region genuinely matches, deny when it genuinely doesn't. Before
    # the fix, EITHER of these would have raised OperationalError.
    assert mediator.search_object(matching_region, "Customer", {"customer_id": "cust_001"}) == ["cust_001"]
    assert mediator.search_object(wrong_region, "Customer", {"customer_id": "cust_001"}) == []


def test_create_without_setting_security_field_produces_an_unreadable_row(mediator, isolated_audit_log):
    # DOCUMENTS a real, known limitation, deliberately not guarded
    # against in v1 -- nothing currently stops a "create" whose
    # mutations never set the type's own security field (region here).
    # Once every create requires an explicit id (see WriteMediator.
    # propose_action()'s own comment on why), this can NO LONGER
    # produce a genuinely orphaned, primary-row-less insert the way it
    # used to -- id_field always resolves to primary storage, so a
    # primary row now always exists, with at least the id set. But the
    # row is still INCOMPLETE (region left NULL), and the practical
    # outcome is the same: still fully unreadable. This test exists so
    # that outcome stays KNOWN and intentional, not silently
    # unverified -- a real candidate for a v2 guard (e.g. requiring
    # every create to set its own security field) if this ever causes
    # a real problem in practice.
    #
    # The ACTUAL outcome is better than it might sound, and this test
    # exists to prove that specifically: the row is not just
    # "partially visible" (risk_score readable, name not) -- it's
    # COMPLETELY unreadable, for every field, including risk_score
    # itself. MAC resolution (_get_security_value()) reads "region"
    # from region's OWN storage -- the primary table -- and finds a
    # real row there, but with region itself NULL, so it returns None,
    # and MAC denies the read before RBAC on risk_score is even
    # reached. A real accidental fail-closed outcome, not a
    # deliberately engineered one -- worth confirming directly rather
    # than assuming.
    #
    # THIS is also the ACTUAL, real-world example
    # log_security_resolution_failed() (core/intermediate_layer/
    # audit.py) was built for, and its own docstring names this test
    # by name as "the clearest real example" -- but until this
    # addition, this test never actually verified the log entry fires
    # here, only that the return values are correctly None. A genuine
    # gap between what the docstring claimed and what was proven.
    write_mediator = WriteMediator(mediator, TEST_ROLES, TEST_ACTION_TYPES)
    alice = _record("alice")

    pending = write_mediator.propose_action(alice, "CreateCustomerRiskOnly",
                                             {"new_id": "cust_incomplete", "risk_score": 0.15})
    outcome = write_mediator.confirm_and_execute(pending, approved=True)

    # The write itself succeeds -- no error, no guard against this today.
    assert outcome["status"] == "written"
    new_id = outcome["object_ids"][0]
    assert new_id == "cust_incomplete"

    # A real primary row DOES exist now (unlike before this session's
    # multi-storage-create work) -- but the object is still COMPLETELY
    # unreadable, since region on that real row is NULL.
    real_adapter = mediator.adapters["primary_sql"]
    raw_region = real_adapter.get_raw_field("Customer", new_id, "region",
                                             {"storage": {"table": "customers", "id_column": "customer_id"}})
    assert raw_region is None, "the primary row should exist but have region unset"

    assert mediator.get_field(alice, "Customer", new_id, "risk_score") is None
    assert mediator.get_field(alice, "Customer", new_id, "name") is None

    # And THIS is the actual, real MDO scenario log_security_resolution_failed()
    # was built for -- confirmed to actually fire here, not just assumed.
    entries = read_audit_log(isolated_audit_log)
    resolution_failed_entries = [
        e for e in entries
        if e["stage"] == "security_resolution_failed" and e["object_id"] == new_id
    ]
    assert len(resolution_failed_entries) >= 1
    assert resolution_failed_entries[0]["object_type"] == "Customer"
