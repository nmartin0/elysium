"""
Tests for core/ontology/sql_adapter.py -- the generic, schema-driven
query engine. Promoted from scratch/scratch_verify_generic_adapter.py
and earlier scratch scripts, now as real assertions against an isolated
test database instead of eyeballed print output.
"""

import pytest

from core.ontology.sql_adapter import search_object, get_field


def test_search_object_finds_matching_org(test_db_path, test_schema):
    result = search_object(test_db_path, test_schema, "org-a", "Author", {"author_id": "auth_001"})
    assert result == ["auth_001"]


def test_search_object_blocks_cross_org(test_db_path, test_schema):
    result = search_object(test_db_path, test_schema, "org-a", "Author", {"author_id": "auth_002"})
    assert result == []


def test_search_object_by_non_id_field(test_db_path, test_schema):
    result = search_object(test_db_path, test_schema, "org-a", "Author", {"name": "Ada Lovelace"})
    assert result == ["auth_001"]


def test_search_object_rejects_unfilterable_field(test_db_path, test_schema):
    with pytest.raises(ValueError):
        search_object(test_db_path, test_schema, "org-a", "Author", {"books": "anything"})


def test_get_field_plain_data(test_db_path, test_schema):
    assert get_field(test_db_path, test_schema, "org-a", "Author", "auth_001", "name") == "Ada Lovelace"


def test_get_field_reverse_link_returns_list_of_ids(test_db_path, test_schema):
    result = get_field(test_db_path, test_schema, "org-a", "Author", "auth_001", "books")
    assert set(result) == {1, 2}  # the two books seeded for auth_001


def test_get_field_forward_link_returns_parent_id(test_db_path, test_schema):
    result = get_field(test_db_path, test_schema, "org-a", "Book", 1, "author_id")
    assert result == "auth_001"


def test_get_field_blocked_cross_org_on_linked_object(test_db_path, test_schema):
    # Book 1 belongs to auth_001 (org-a) -- requesting as org-b must be blocked,
    # even though the request targets the Book, not the Author directly.
    result = get_field(test_db_path, test_schema, "org-b", "Book", 1, "title")
    assert result is None


def test_get_field_allowed_same_org_on_linked_object(test_db_path, test_schema):
    result = get_field(test_db_path, test_schema, "org-a", "Book", 1, "title")
    assert result == "Notes on the Analytical Engine"


def test_get_field_unknown_field_raises(test_db_path, test_schema):
    with pytest.raises(ValueError):
        get_field(test_db_path, test_schema, "org-a", "Author", "auth_001", "nonexistent_field")
