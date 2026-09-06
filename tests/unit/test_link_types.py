"""
Point 16: link types as first-class ontology entities.

FOUNDRY'S MODEL, adopted directly: a link type is "the schema
definition of a relationship between two object types" -- an entity in
its own right, not an attribute of a field. It names both object
types, their cardinality, and how the relationship is backed:
a FOREIGN KEY for one-to-one and one-to-many ("a property of one
object type refers to the primary key property of the other"), or a
JOIN TABLE for many-to-many ("a table containing pairs of primary
keys").

WHAT THIS REPLACED. Links were previously declared as field
attributes, once per DIRECTION, so Customer.transactions and
Transaction.customer_id were unrelated declarations of ONE
relationship. Four limitations followed, and all four are closed here:
no many-to-many at all, directions that could drift apart, no link
metadata, and nowhere for a relationship's own identity.
"""

import pytest

from core.ontology.link_types import expand_link_types, validate_link_types

OBJECT_TYPES = {
    "Customer": {
        "storage": {"silo": "primary", "table": "customers", "id_column": "customer_id"},
        "id_field": "customer_id",
        "fields": {"name": {"type": "data"}},
    },
    "Order": {
        "storage": {"silo": "primary", "table": "orders", "id_column": "order_id"},
        "id_field": "order_id",
        "fields": {"total": {"type": "data"}},
    },
    "Tag": {
        "storage": {"silo": "primary", "table": "tags", "id_column": "tag_id"},
        "id_field": "tag_id",
        "fields": {"label": {"type": "data"}},
    },
}

ONE_TO_MANY = {
    "CustomerOrders": {
        "display_name": "Orders",
        "source": {"object_type": "Customer", "api_name": "orders"},
        "target": {"object_type": "Order", "api_name": "customer_id"},
        "cardinality": "one_to_many",
        "foreign_key_column": "customer_id",
    }
}

MANY_TO_MANY = {
    "CustomerTags": {
        "source": {"object_type": "Customer", "api_name": "tags"},
        "target": {"object_type": "Tag", "api_name": "customers"},
        "cardinality": "many_to_many",
        "join_table": {
            "table": "customer_tags",
            "source_column": "customer_id",
            "target_column": "tag_id",
        },
    }
}


def test_one_declaration_generates_both_directions(expected=None):
    # THE limitation this design closes. Two independent field
    # declarations could drift apart; one link type cannot.
    expanded = expand_link_types(ONE_TO_MANY, OBJECT_TYPES)

    forward = expanded["Customer"]["fields"]["orders"]
    backward = expanded["Order"]["fields"]["customer_id"]

    assert forward["target"] == "Order"
    assert forward["cardinality"] == "many"
    assert backward["target"] == "Customer"
    assert backward["cardinality"] == "one"
    assert forward["link_type"] == backward["link_type"] == "CustomerOrders"


def test_a_foreign_key_link_traverses_the_targets_own_table(expected=None):
    expanded = expand_link_types(ONE_TO_MANY, OBJECT_TYPES)

    forward = expanded["Customer"]["fields"]["orders"]

    assert forward["via_table"] == "orders"
    assert forward["via_column"] == "customer_id"
    # A foreign-key link declares no via_target_column: the target's
    # own id column is what comes back.
    assert "via_target_column" not in forward


def test_a_many_to_many_link_traverses_a_join_table_in_both_directions():
    # The capability the old form could not express AT ALL: neither
    # object can hold the other's key without duplicating rows.
    expanded = expand_link_types(MANY_TO_MANY, OBJECT_TYPES)

    forward = expanded["Customer"]["fields"]["tags"]
    backward = expanded["Tag"]["fields"]["customers"]

    assert forward["via_table"] == backward["via_table"] == "customer_tags"
    # Both traverse the SAME table, differing only in which column is
    # matched and which is returned.
    assert forward["via_column"] == "customer_id"
    assert forward["via_target_column"] == "tag_id"
    assert backward["via_column"] == "tag_id"
    assert backward["via_target_column"] == "customer_id"
    assert forward["cardinality"] == backward["cardinality"] == "many"


def test_link_metadata_reaches_both_generated_fields():
    # Point 10 gave object types and fields display names; links got
    # none, so a UI rendered "owner_customer_id".
    expanded = expand_link_types(ONE_TO_MANY, OBJECT_TYPES)

    assert expanded["Customer"]["fields"]["orders"]["display_name"] == "Orders"
    assert expanded["Order"]["fields"]["customer_id"]["display_name"] == "Orders"


def test_an_undeclared_display_name_is_omitted_not_nulled():
    # A null would override humanize()'s fallback with nothing, leaving
    # a UI with a blank label.
    expanded = expand_link_types(MANY_TO_MANY, OBJECT_TYPES)

    assert "display_name" not in expanded["Customer"]["fields"]["tags"]


def test_expansion_leaves_the_original_object_types_untouched():
    # Mutating the caller's dict would make load order matter.
    before = dict(OBJECT_TYPES["Customer"]["fields"])

    expand_link_types(ONE_TO_MANY, OBJECT_TYPES)

    assert OBJECT_TYPES["Customer"]["fields"] == before


# --- Validation ---------------------------------------------------------


def test_a_valid_link_type_validates():
    validate_link_types(ONE_TO_MANY, OBJECT_TYPES)
    validate_link_types(MANY_TO_MANY, OBJECT_TYPES)


def test_an_unknown_object_type_is_rejected():
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"],
                 "target": {"object_type": "NoSuchType", "api_name": "x"}}}

    with pytest.raises(ValueError, match="not a declared object type"):
        validate_link_types(bad, OBJECT_TYPES)


def test_an_unknown_cardinality_is_rejected():
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"], "cardinality": "some_to_some"}}

    with pytest.raises(ValueError, match="cardinality must be one of"):
        validate_link_types(bad, OBJECT_TYPES)


def test_many_to_many_without_a_join_table_is_rejected():
    bad = {"L": {**MANY_TO_MANY["CustomerTags"]}}
    del bad["L"]["join_table"]

    with pytest.raises(ValueError, match="requires a join_table"):
        validate_link_types(bad, OBJECT_TYPES)


def test_a_foreign_key_link_without_a_column_is_rejected():
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"]}}
    del bad["L"]["foreign_key_column"]

    with pytest.raises(ValueError, match="requires a foreign_key_column"):
        validate_link_types(bad, OBJECT_TYPES)


def test_declaring_both_backings_is_rejected():
    # A link is backed one way or the other; declaring both means the
    # author is unsure, and guessing which they meant would be worse
    # than saying so.
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"],
                 "join_table": {"table": "x", "source_column": "a", "target_column": "b"}}}

    with pytest.raises(ValueError, match="must not declare a join_table"):
        validate_link_types(bad, OBJECT_TYPES)


def test_an_api_name_colliding_with_a_real_field_is_rejected():
    # The generated link field would silently shadow the data field.
    bad = {"L": {**ONE_TO_MANY["CustomerOrders"],
                 "target": {"object_type": "Order", "api_name": "total"}}}

    with pytest.raises(ValueError, match="collides with a field"):
        validate_link_types(bad, OBJECT_TYPES)


def test_a_missing_side_is_rejected():
    bad = {"L": {"cardinality": "one_to_many", "foreign_key_column": "x",
                 "source": {"object_type": "Customer", "api_name": "orders"}}}

    with pytest.raises(ValueError, match="missing 'target'"):
        validate_link_types(bad, OBJECT_TYPES)
