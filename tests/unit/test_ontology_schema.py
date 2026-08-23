"""Tests for core/ontology/schema.py -- generic schema introspection."""

import pytest

from core.ontology.schema import get_id_field, get_field_info, is_link_field, get_link_target


def test_get_id_field_returns_declared_id(test_schema):
    assert get_id_field(test_schema, "Author") == "author_id"


def test_get_id_field_unknown_object_type_raises(test_schema):
    with pytest.raises(ValueError):
        get_id_field(test_schema, "Nonexistent")


def test_get_field_info_returns_field_dict(test_schema):
    info = get_field_info(test_schema, "Author", "name")
    assert info == {"type": "data"}


def test_get_field_info_unknown_field_raises(test_schema):
    with pytest.raises(ValueError):
        get_field_info(test_schema, "Author", "nonexistent_field")


def test_is_link_field_true_for_link(test_schema):
    info = get_field_info(test_schema, "Author", "books")
    assert is_link_field(info) is True


def test_is_link_field_false_for_data(test_schema):
    info = get_field_info(test_schema, "Author", "name")
    assert is_link_field(info) is False


def test_get_link_target_returns_target_type(test_schema):
    info = get_field_info(test_schema, "Author", "books")
    assert get_link_target(info) == "Book"
