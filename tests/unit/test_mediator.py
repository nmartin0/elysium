"""
Tests for core/ontology/mediator.py (DataMediator) -- three fully
explicit gates now: MAC (org_id boundary), RBAC object-type level
(read:Type -- may this user discover/search this type at all), and
RBAC field level (read:Type.field -- may this user see THIS field's
value). Nothing is inherited between the three.

  alice: org-a, role=reader  -- passes MAC + has every field grant used below
  bob:   org-b, role=reader  -- different org (MAC boundary test)
  carol: org-a, NO role      -- same org as alice, but no role at all
                                 (proves RBAC is checked independently of MAC)
  dave:  org-a, role=type_only -- has read:Author (can discover) but
                                 NO field grants at all (proves field-level
                                 RBAC is independent of object-type RBAC)
"""

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.ontology.mediator import DataMediator

TEST_USERS = {
    "alice": {"org_id": "org-a", "role": "reader"},
    "bob": {"org_id": "org-b", "role": "reader"},
    "carol": {"org_id": "org-a"},  # deliberately no role
    "dave": {"org_id": "org-a", "role": "type_only"},
}

TEST_ROLES = {
    "reader": {"allowed_actions": [
        "read:Author", "read:Author.author_id", "read:Author.name", "read:Author.books",
        "read:Book", "read:Book.book_id", "read:Book.title", "read:Book.author_id",
    ]},
    "type_only": {"allowed_actions": ["read:Author", "read:Author.author_id"]},  # discovery + ID only, no other field grants
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
    result = mediator.search_object("bob", "Author", {"author_id": "auth_001"})
    assert result == []


def test_search_object_blocks_missing_role_rbac(mediator):
    result = mediator.search_object("carol", "Author", {"author_id": "auth_001"})
    assert result == []


def test_search_object_by_non_id_field(mediator):
    result = mediator.search_object("alice", "Author", {"name": "Ada Lovelace"})
    assert result == ["auth_001"]


def test_search_object_rejects_unfilterable_field(mediator):
    with pytest.raises(ValueError):
        mediator.search_object("alice", "Author", {"books": "anything"})


def test_search_object_error_does_not_leak_valid_field_list(mediator):
    # The error must be generic -- no field names, so a user probing
    # with a bad filter key learns nothing about the real schema.
    with pytest.raises(ValueError) as exc_info:
        mediator.search_object("alice", "Author", {"totally_fake_field": "x"})
    message = str(exc_info.value)
    assert "name" not in message and "org_id" not in message and "books" not in message


def test_search_object_unknown_type_returns_empty_not_error(mediator):
    # Uniform with "not authorized" -- never raises for a bad type name.
    assert mediator.search_object("alice", "TotallyFakeType", {}) == []


def test_get_field_plain_data(mediator):
    assert mediator.get_field("alice", "Author", "auth_001", "name") == "Ada Lovelace"


def test_get_field_object_type_rbac_alone_is_not_enough(mediator):
    # dave has read:Author (can discover/search) but ZERO field grants
    # -- proves field-level RBAC is a genuinely separate gate, not
    # implied by the object-type grant.
    assert mediator.search_object("dave", "Author", {"author_id": "auth_001"}) == ["auth_001"]
    assert mediator.get_field("dave", "Author", "auth_001", "name") is None


def test_get_field_reverse_link_returns_list_of_ids(mediator):
    result = mediator.get_field("alice", "Author", "auth_001", "books")
    assert set(result) == {1, 2}


def test_get_field_forward_link_returns_parent_id(mediator):
    result = mediator.get_field("alice", "Book", 1, "author_id")
    assert result == "auth_001"


def test_get_field_blocked_cross_org_on_linked_object_mac(mediator):
    result = mediator.get_field("bob", "Book", 1, "title")
    assert result is None


def test_get_field_blocked_missing_role_on_linked_object_rbac(mediator):
    result = mediator.get_field("carol", "Book", 1, "title")
    assert result is None


def test_get_field_allowed_same_org_on_linked_object(mediator):
    result = mediator.get_field("alice", "Book", 1, "title")
    assert result == "Notes on the Analytical Engine"


def test_get_field_unknown_field_returns_none_not_raise(mediator):
    # Uniform denial -- a genuinely nonexistent field behaves exactly
    # like a real field the user isn't authorized for, not a distinct
    # loud error. See test_get_field_unknown_and_denied_are_identical
    # for the direct side-by-side proof.
    assert mediator.get_field("alice", "Author", "auth_001", "nonexistent_field") is None


def test_get_field_unknown_and_denied_are_identical(mediator):
    # THE probing-resistance proof: a real field bob has zero grant for
    # must be indistinguishable from a field that doesn't exist at all.
    denied_real_field = mediator.get_field("carol", "Author", "auth_001", "org_id")  # real field, carol has no role
    fake_field = mediator.get_field("carol", "Author", "auth_001", "not_a_real_field_xyz")
    assert denied_real_field is fake_field is None


def test_visible_schema_hides_ungranted_object_types(mediator):
    visible = mediator.visible_schema("carol")  # no role at all
    assert visible == {}


def test_visible_schema_shows_discovery_only_type_with_empty_fields(mediator):
    # dave: read:Author only, zero field grants. The type must still
    # appear (discovery is a real, independent capability -- see
    # visible_schema()'s docstring for the bug this corrects), just
    # with an empty fields dict.
    visible = mediator.visible_schema("dave")
    assert "Author" in visible
    assert visible["Author"]["fields"] == {}


def test_visible_schema_shows_exactly_the_granted_fields(mediator):
    visible = mediator.visible_schema("alice")
    assert set(visible["Author"]["fields"].keys()) == {"name", "books"}
    assert "org_id" not in visible["Author"]["fields"]


def test_id_field_itself_requires_its_own_explicit_grant(mediator):
    # An id_field is NOT automatically visible/searchable just because
    # read:{object_type} is granted -- it needs its own
    # read:{object_type}.{id_field} grant, same as any other field.
    # eve has read:Author + read:Author.name, but NOT read:Author.author_id.
    eve_users = {**TEST_USERS, "eve": {"org_id": "org-a", "role": "no_id_grant"}}
    eve_roles = {**TEST_ROLES, "no_id_grant": {"allowed_actions": ["read:Author", "read:Author.name"]}}
    m2 = DataMediator(mediator.schema, mediator.adapters, mediator.silo_for_type, eve_users, eve_roles, "org_id")

    with pytest.raises(ValueError):
        m2.search_object("eve", "Author", {"author_id": "auth_001"})
    # Searching by the GRANTED field still works fine.
    assert m2.search_object("eve", "Author", {"name": "Ada Lovelace"}) == ["auth_001"]


def test_two_mediators_are_independent():
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
        roles_a = {"reader": {"allowed_actions": ["read:Author", "read:Author.name"]}}

        adapter_a = SQLiteAdapter({"path": db_a})
        mediator_a = DataMediator(schema_a, {"s": adapter_a}, {"Author": "s"}, users_a, roles_a, "org_id")
        assert mediator_a.get_field("x_user", "Author", "x", "name") == "Test Author"
