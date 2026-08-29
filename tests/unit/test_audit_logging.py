"""
Tests for the audit-log distinctions added alongside MDO:
log_unknown_reference() and log_security_resolution_failed()
(core/intermediate_layer/audit.py). Both are purely ADDITIVE --
neither replaces or reorders the existing access_check entry
log_access() already writes on every decision; these tests confirm
that explicitly, not just that the new entries appear.

The underlying principle these implement is a standard security
pattern, not a project invention: fail UNIFORMLY to the requester
(already true and unchanged -- get_field()/search_object() still
return None/[] identically either way), while logging the REAL reason
for an operator. See audit.py's own module docstring.

Uses tests/conftest.py's shared Author/Book schema and
isolated_audit_log fixture.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.intermediate_layer.auth import resolve_user_record
from core.ontology.mediator import DataMediator
from tests.conftest import read_audit_log

TEST_ROLES = {
    "reader": {"allowed_actions": [
        "read:Author", "read:Author.author_id", "read:Author.name",
    ]},
}

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},  # wrong org, for the ordinary-MAC-mismatch test
}


def _record(user_id):
    return resolve_user_record(TEST_USERS, user_id, "org_id")


@pytest.fixture
def mediator(test_db_path, test_schema) -> DataMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in test_schema.items()}
    return DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_ROLES)


def test_unknown_field_on_get_field_logs_both_entries(mediator, isolated_audit_log):
    # THE regression test for the real ordering bug found while
    # verifying this mechanism directly: a made-up field name almost
    # always makes check_access() itself return False (no role grants
    # a nonexistent action string), which would make an early "return
    # None" on that alone leave this unreachable in the COMMON case --
    # exactly the case (a model guessing at a field name) this exists
    # to catch. Both entries must appear -- this is additive, not a
    # replacement for the existing access_check entry.
    mediator.get_field(_record("alice"), "Author", "auth_001", "totally_fake_field")

    entries = read_audit_log(isolated_audit_log)
    access_check_entries = [e for e in entries if e["stage"] == "access_check"]
    unknown_ref_entries = [e for e in entries if e["stage"] == "unknown_reference"]

    assert len(access_check_entries) == 1
    assert access_check_entries[0]["rbac_allowed"] is False

    assert len(unknown_ref_entries) == 1
    assert unknown_ref_entries[0]["object_type"] == "Author"
    assert unknown_ref_entries[0]["field_name"] == "totally_fake_field"


def test_unknown_object_type_on_get_field_logs_unknown_reference(mediator, isolated_audit_log):
    mediator.get_field(_record("alice"), "TotallyFakeType", "auth_001", "name")

    entries = read_audit_log(isolated_audit_log)
    unknown_ref_entries = [e for e in entries if e["stage"] == "unknown_reference"]

    assert len(unknown_ref_entries) == 1
    assert unknown_ref_entries[0]["object_type"] == "TotallyFakeType"
    assert unknown_ref_entries[0]["field_name"] is None
    # No access_check entry at all -- check_access() is never reached
    # for a completely unknown object_type.
    assert not any(e["stage"] == "access_check" for e in entries)


def test_unknown_object_type_on_search_object_logs_unknown_reference(mediator, isolated_audit_log):
    result = mediator.search_object(_record("alice"), "AlsoFakeType", {})

    assert result == []
    entries = read_audit_log(isolated_audit_log)
    unknown_ref_entries = [e for e in entries if e["stage"] == "unknown_reference"]
    assert len(unknown_ref_entries) == 1
    assert unknown_ref_entries[0]["object_type"] == "AlsoFakeType"


def test_real_type_denied_at_object_type_level_is_now_logged(mediator, isolated_audit_log):
    # A REAL type, but read:Author was never granted at all -- this
    # gate previously produced NO log entry whatsoever (check_access(),
    # which needs a specific object_id, is never reached for this
    # object-type-level check). Now reuses log_access()'s own existing
    # shape directly (object_id=None, mac_allowed=None -- MAC
    # genuinely doesn't apply without a specific object).
    no_role_user = resolve_user_record({"carol": {"org_id": "org-a"}}, "carol", "org_id")
    result = mediator.search_object(no_role_user, "Author", {})

    assert result == []
    entries = read_audit_log(isolated_audit_log)
    access_check_entries = [e for e in entries if e["stage"] == "access_check"]
    assert len(access_check_entries) == 1
    assert access_check_entries[0]["object_id"] is None
    assert access_check_entries[0]["mac_allowed"] is None
    assert access_check_entries[0]["rbac_allowed"] is False
    # And genuinely NOT an unknown_reference entry -- Author is real.
    assert not any(e["stage"] == "unknown_reference" for e in entries)


def test_ordinary_mac_mismatch_does_not_log_security_resolution_failed(mediator, isolated_audit_log):
    # bob is a real user, in a real org, asking about a real object
    # that genuinely belongs to a DIFFERENT org -- an ordinary,
    # expected MAC denial. Must NOT trigger
    # log_security_resolution_failed(), since the security value WAS
    # resolved correctly (just didn't match) -- that distinction is
    # the entire point of this mechanism.
    mediator.get_field(_record("bob"), "Author", "auth_001", "name")

    entries = read_audit_log(isolated_audit_log)
    assert not any(e["stage"] == "security_resolution_failed" for e in entries)
    access_check_entries = [e for e in entries if e["stage"] == "access_check"]
    assert access_check_entries[0]["mac_allowed"] is False


def test_orphaned_mdo_style_record_logs_security_resolution_failed(tmp_path, isolated_audit_log):
    # A genuine security-resolution FAILURE, not an ordinary mismatch
    # -- an object whose security field cannot be resolved at all
    # (here, simulated directly: an Author row that simply doesn't
    # exist, the same underlying condition an orphaned MDO record
    # produces -- see tests/unit/test_mdo.py's own orphaned-record
    # test for the real MDO case this generalizes from).
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE authors (author_id TEXT PRIMARY KEY, org_id TEXT NOT NULL, name TEXT NOT NULL);
        CREATE TABLE books (
            book_id INTEGER PRIMARY KEY, author_id TEXT NOT NULL, title TEXT NOT NULL, year INTEGER NOT NULL
        );
    """)
    conn.commit()
    conn.close()

    from tests.conftest import TEST_SCHEMA
    adapter = SQLiteAdapter({"path": db_path})
    silo_for_type = {object_type: type_def["storage"]["silo"] for object_type, type_def in TEST_SCHEMA.items()}
    empty_mediator = DataMediator(TEST_SCHEMA, {"test_silo": adapter}, silo_for_type, TEST_ROLES)

    # auth_999 genuinely does not exist in this empty database at all.
    empty_mediator.get_field(_record("alice"), "Author", "auth_999_nonexistent", "name")

    entries = read_audit_log(isolated_audit_log)
    resolution_failed_entries = [e for e in entries if e["stage"] == "security_resolution_failed"]
    assert len(resolution_failed_entries) == 1
    assert resolution_failed_entries[0]["object_type"] == "Author"
    assert resolution_failed_entries[0]["object_id"] == "auth_999_nonexistent"
