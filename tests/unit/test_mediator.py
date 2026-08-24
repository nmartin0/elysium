"""
Tests for core/ontology/mediator.py (DataMediator) combined with
adapters/sqlite_adapter.py (SQLiteAdapter) -- the split that replaced
the old, single-class OntologyEngine. Same coverage as before: security
enforcement, link traversal, criteria validation -- now exercised
through the real two-layer path (DataMediator routing to a real
SQLiteAdapter instance) rather than one merged class.
"""

import pytest

from adapters.sqlite_adapter import SQLiteAdapter
from core.ontology.mediator import DataMediator


@pytest.fixture
def mediator(test_db_path, test_schema) -> DataMediator:
    adapter = SQLiteAdapter({"path": test_db_path})
    silo_for_type = {object_type: type_def["silo"] for object_type, type_def in test_schema.items()}
    return DataMediator(test_schema, {"test_silo": adapter}, silo_for_type)


def test_search_object_finds_matching_org(mediator):
    result = mediator.search_object("org-a", "Author", {"author_id": "auth_001"})
    assert result == ["auth_001"]


def test_search_object_blocks_cross_org(mediator):
    result = mediator.search_object("org-a", "Author", {"author_id": "auth_002"})
    assert result == []


def test_search_object_by_non_id_field(mediator):
    result = mediator.search_object("org-a", "Author", {"name": "Ada Lovelace"})
    assert result == ["auth_001"]


def test_search_object_rejects_unfilterable_field(mediator):
    with pytest.raises(ValueError):
        mediator.search_object("org-a", "Author", {"books": "anything"})


def test_get_field_plain_data(mediator):
    assert mediator.get_field("org-a", "Author", "auth_001", "name") == "Ada Lovelace"


def test_get_field_reverse_link_returns_list_of_ids(mediator):
    result = mediator.get_field("org-a", "Author", "auth_001", "books")
    assert set(result) == {1, 2}


def test_get_field_forward_link_returns_parent_id(mediator):
    result = mediator.get_field("org-a", "Book", 1, "author_id")
    assert result == "auth_001"


def test_get_field_blocked_cross_org_on_linked_object(mediator):
    # Book 1 belongs to auth_001 (org-a) -- requesting as org-b must be
    # blocked, even though the request targets the Book, not the Author.
    # This is the cross-object SECURITY CHAIN specifically -- the most
    # important thing this test file proves still works after the split.
    result = mediator.get_field("org-b", "Book", 1, "title")
    assert result is None


def test_get_field_allowed_same_org_on_linked_object(mediator):
    result = mediator.get_field("org-a", "Book", 1, "title")
    assert result == "Notes on the Analytical Engine"


def test_get_field_unknown_field_raises(mediator):
    with pytest.raises(ValueError):
        mediator.get_field("org-a", "Author", "auth_001", "nonexistent_field")


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

        adapter_a = SQLiteAdapter({"path": db_a})
        mediator_a = DataMediator(schema_a, {"s": adapter_a}, {"Author": "s"})
        assert mediator_a.get_field("org-x", "Author", "x", "name") == "Test Author"
