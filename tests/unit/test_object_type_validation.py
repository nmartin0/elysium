"""
Tests for core/ontology/object_type_validation.py's
validate_object_types() -- schema-load-time validation for the
OPTIONAL, per-object-type title_field.
"""

import pytest

from core.ontology.object_type_validation import validate_object_types


def _object_type(id_field="widget_id", title_field=None, fields=None):
    type_def = {"id_field": id_field, "fields": fields or {"name": {"type": "data"}}}
    if title_field is not None:
        type_def["title_field"] = title_field
    return type_def


def test_no_title_field_declared_is_fine():
    validate_object_types({"Widget": _object_type()})  # does not raise


def test_title_field_referencing_a_real_data_field_is_valid():
    validate_object_types({"Widget": _object_type(title_field="name")})  # does not raise


def test_title_field_referencing_the_id_field_itself_is_valid():
    # A real, legitimate case -- see this module's own docstring for
    # why the id_field is a completely valid, if unglamorous, target.
    validate_object_types({"Widget": _object_type(title_field="widget_id")})  # does not raise


def test_title_field_referencing_unknown_field_is_rejected():
    with pytest.raises(ValueError, match="unknown field"):
        validate_object_types({"Widget": _object_type(title_field="totally_fake_field")})


def test_title_field_referencing_a_link_field_is_rejected():
    fields = {"name": {"type": "data"}, "owner": {"type": "link", "target": "Person", "cardinality": "one"}}
    with pytest.raises(ValueError, match="not a link"):
        validate_object_types({"Widget": _object_type(title_field="owner", fields=fields)})


def test_a_valid_title_field_does_not_hide_an_invalid_one_on_a_different_type():
    object_types = {
        "Widget": _object_type(title_field="name"),
        "Gadget": _object_type(id_field="gadget_id", title_field="totally_fake_field"),
    }
    with pytest.raises(ValueError, match="Gadget"):
        validate_object_types(object_types)
