"""Tests for core/ontology/schema.py -- generic schema introspection."""

import pytest

from core.ontology.schema import (
    get_id_field, get_field_info, is_link_field, get_link_target, is_searchable_field,
    get_field_storage_name, get_field_column,
)


def test_get_id_field_returns_declared_id(test_schema):
    assert get_id_field(test_schema, "Author") == "author_id"


def test_get_id_field_unknown_object_type_raises(test_schema):
    with pytest.raises(ValueError):
        get_id_field(test_schema, "Nonexistent")


def test_get_field_info_returns_field_dict(test_schema):
    field_info = get_field_info(test_schema, "Author", "name")
    assert field_info == {"type": "data"}


def test_get_field_info_unknown_field_raises(test_schema):
    with pytest.raises(ValueError):
        get_field_info(test_schema, "Author", "nonexistent_field")


def test_is_link_field_true_for_link(test_schema):
    field_info = get_field_info(test_schema, "Author", "books")
    assert is_link_field(field_info) is True


def test_is_link_field_false_for_data(test_schema):
    field_info = get_field_info(test_schema, "Author", "name")
    assert is_link_field(field_info) is False


def test_get_link_target_returns_target_type(test_schema):
    field_info = get_field_info(test_schema, "Author", "books")
    assert get_link_target(field_info) == "Book"


def test_is_searchable_field_true_for_data(test_schema):
    field_info = get_field_info(test_schema, "Author", "name")
    assert is_searchable_field(field_info) is True


def test_is_searchable_field_true_for_forward_link(test_schema):
    # Book.author_id is a link with cardinality "one" -- a real column,
    # searchable.
    field_info = get_field_info(test_schema, "Book", "author_id")
    assert is_searchable_field(field_info) is True


def test_is_searchable_field_false_for_reverse_link(test_schema):
    # Author.books is a link with cardinality "many" -- computed, not a
    # real column, NOT searchable.
    field_info = get_field_info(test_schema, "Author", "books")
    assert is_searchable_field(field_info) is False


def test_get_field_storage_name_returns_none_for_a_field_with_no_override(test_schema):
    # test_schema's fields (Author.name, Book.title, etc.) predate MDO
    # entirely and declare no "storage" key at all -- this is the
    # overwhelmingly common case, and MUST resolve to None (meaning
    # "use the type's own primary storage"), not raise or return
    # something else.
    field_info = get_field_info(test_schema, "Author", "name")
    assert get_field_storage_name(field_info) is None


def test_get_field_storage_name_returns_the_declared_override():
    field_info = {"type": "data", "storage": "risk_db", "column": "score_val"}
    assert get_field_storage_name(field_info) == "risk_db"


def test_get_field_column_defaults_to_the_field_name_itself(test_schema):
    # No "column" override declared -- must default to the field name,
    # matching every field's behavior before MDO's "column" key existed.
    field_info = get_field_info(test_schema, "Author", "name")
    assert get_field_column(field_info, "name") == "name"


def test_get_field_column_returns_the_declared_override():
    field_info = {"type": "data", "storage": "risk_db", "column": "score_val"}
    assert get_field_column(field_info, "risk_score") == "score_val"
