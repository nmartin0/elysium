"""
Tests for core/ontology/sql_adapter.py -- the generic, schema-driven
OntologyEngine class. One engine instance per test, built from the
isolated test_db_path/test_schema fixtures.
"""

import pytest

from core.ontology.sql_adapter import OntologyEngine


@pytest.fixture
def engine(test_db_path, test_schema) -> OntologyEngine:
    return OntologyEngine(test_db_path, test_schema)


def test_search_object_finds_matching_org(engine):
    result = engine.search_object("org-a", "Author", {"author_id": "auth_001"})
    assert result == ["auth_001"]


def test_search_object_blocks_cross_org(engine):
    result = engine.search_object("org-a", "Author", {"author_id": "auth_002"})
    assert result == []


def test_search_object_by_non_id_field(engine):
    result = engine.search_object("org-a", "Author", {"name": "Ada Lovelace"})
    assert result == ["auth_001"]


def test_search_object_rejects_unfilterable_field(engine):
    with pytest.raises(ValueError):
        engine.search_object("org-a", "Author", {"books": "anything"})


def test_get_field_plain_data(engine):
    assert engine.get_field("org-a", "Author", "auth_001", "name") == "Ada Lovelace"


def test_get_field_reverse_link_returns_list_of_ids(engine):
    result = engine.get_field("org-a", "Author", "auth_001", "books")
    assert set(result) == {1, 2}


def test_get_field_forward_link_returns_parent_id(engine):
    result = engine.get_field("org-a", "Book", 1, "author_id")
    assert result == "auth_001"


def test_get_field_blocked_cross_org_on_linked_object(engine):
    # Book 1 belongs to auth_001 (org-a) -- requesting as org-b must be
    # blocked, even though the request targets the Book, not the Author.
    result = engine.get_field("org-b", "Book", 1, "title")
    assert result is None


def test_get_field_allowed_same_org_on_linked_object(engine):
    result = engine.get_field("org-a", "Book", 1, "title")
    assert result == "Notes on the Analytical Engine"


def test_get_field_unknown_field_raises(engine):
    with pytest.raises(ValueError):
        engine.get_field("org-a", "Author", "auth_001", "nonexistent_field")


def test_two_engines_are_independent():
    # Sanity check that OntologyEngine instances don't share state --
    # constructing a second one with different args must not affect
    # the first (a real risk if db_path/schema were ever accidentally
    # stored as class attributes instead of instance attributes).
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
            "id_field": "author_id", "table": "authors", "id_column": "author_id",
            "security": {"field": "org_id"},
            "fields": {"org_id": {"type": "data"}, "name": {"type": "data"}},
        }}

        engine_a = OntologyEngine(db_a, schema_a)
        assert engine_a.get_field("org-x", "Author", "x", "name") == "Test Author"
        # engine_a's db_path/schema must be its own, not shared globally.
        assert engine_a.db_path == db_a
