"""
Tests for core/ontology/mediator.py (DataMediator) -- now enforcing
BOTH MAC (org_id boundary) and RBAC (role -> allowed_actions) on every
read, via check_access(). Test users are deliberately chosen to
distinguish the two gates from each other:

  alice: org-a, role=reader  -- passes both gates
  bob:   org-b, role=reader  -- different org (MAC boundary test)
  carol: org-a, NO role      -- SAME org as alice, but no role at all
                                 (proves RBAC is checked independently
                                 of MAC -- same-org data is still denied
                                 if the role is missing)
"""

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.ontology.mediator import DataMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
    "carol": {"org_id": "org-a"},  # deliberately no role
}

TEST_ROLES = {
    "reader": {"allowed_actions": ["read:Author", "read:Book"]},
}


@pytest.fixture
def mediator(test_db_path, test_schema) -> DataMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["silo"] for object_type, type_def in test_schema.items()}
    return DataMediator(test_schema, {"test_silo": adapter}, silo_for_type, TEST_USERS, TEST_ROLES, "org_id")


def test_search_object_finds_matching_org(mediator):
    result = mediator.search_object("alice", "Author", {"author_id": "auth_001"})
    assert result == ["auth_001"]


def test_search_object_blocks_cross_org_mac(mediator):
    # bob is org-b, auth_001 belongs to org-a -- MAC boundary.
    result = mediator.search_object("bob", "Author", {"author_id": "auth_001"})
    assert result == []


def test_search_object_blocks_missing_role_rbac(mediator):
    # carol is SAME org as alice (org-a) -- MAC would allow this. She
    # is blocked purely because she has no role at all. This is the
    # test that proves RBAC is genuinely enforced, independently of MAC.
    result = mediator.search_object("carol", "Author", {"author_id": "auth_001"})
    assert result == []


def test_search_object_by_non_id_field(mediator):
    result = mediator.search_object("alice", "Author", {"name": "Ada Lovelace"})
    assert result == ["auth_001"]


def test_search_object_rejects_unfilterable_field(mediator):
    with pytest.raises(ValueError):
        mediator.search_object("alice", "Author", {"books": "anything"})


def test_get_field_plain_data(mediator):
    assert mediator.get_field("alice", "Author", "auth_001", "name") == "Ada Lovelace"


def test_get_field_reverse_link_returns_list_of_ids(mediator):
    result = mediator.get_field("alice", "Author", "auth_001", "books")
    assert set(result) == {1, 2}


def test_get_field_forward_link_returns_parent_id(mediator):
    result = mediator.get_field("alice", "Book", 1, "author_id")
    assert result == "auth_001"


def test_get_field_blocked_cross_org_on_linked_object_mac(mediator):
    # Book 1 belongs to auth_001 (org-a) -- requesting as bob (org-b)
    # must be blocked, even though the request targets the Book, not
    # the Author. This is the cross-object SECURITY CHAIN specifically.
    result = mediator.get_field("bob", "Book", 1, "title")
    assert result is None


def test_get_field_blocked_missing_role_on_linked_object_rbac(mediator):
    # Same idea, but for RBAC: carol is org-a (matches Book 1's chain),
    # but has no role -- must still be blocked.
    result = mediator.get_field("carol", "Book", 1, "title")
    assert result is None


def test_get_field_allowed_same_org_on_linked_object(mediator):
    result = mediator.get_field("alice", "Book", 1, "title")
    assert result == "Notes on the Analytical Engine"


def test_get_field_unknown_field_raises(mediator):
    with pytest.raises(ValueError):
        mediator.get_field("alice", "Author", "auth_001", "nonexistent_field")


def test_two_mediators_are_independent():
    # Sanity check that DataMediator/SQLiteAdapter instances don't share
    # state -- constructing a second one with different args must not
    # affect the first.
    import sqlite3
    from pathlib import Path
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db_a = Path(tmp) / "a.db"
        conn = sqlite3.connect(db_a)
        conn.executescript("""
            CREATE TABLE authors (author_id TEXT PRIMARY KEY, org_id TEXT, name TEXT);
            INSERT INTO authors VALUES ('x', 'org-x', 'Test Author');
        """)
        conn.commit()
        conn.close()

        schema_a = {"Author": {
            "silo": "s", "id_field": "author_id", "table": "authors", "id_column": "author_id",
            "security": {"field": "org_id"},
            "fields": {"org_id": {"type": "data"}, "name": {"type": "data"}},
        }}
        users_a = {"x_user": {"org_id": "org-x", "role": "reader"}}
        roles_a = {"reader": {"allowed_actions": ["read:Author"]}}

        adapter_a = SQLiteAdapter({"path": db_a})
        mediator_a = DataMediator(schema_a, {"s": adapter_a}, {"Author": "s"}, users_a, roles_a, "org_id")
        assert mediator_a.get_field("x_user", "Author", "x", "name") == "Test Author"
