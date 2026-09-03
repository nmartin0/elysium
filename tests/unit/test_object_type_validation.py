"""
Tests for core/ontology/object_type_validation.py's
validate_object_types() -- schema-load-time validation for the
OPTIONAL, per-object-type title_field, AND the MANDATORY, per-
object-type security.field/security.via_field (the MAC boundary
itself). See that module's own docstring for the full reasoning
behind both, especially the four-part gap the security validation
closes.
"""

import pytest

from core.ontology.object_type_validation import validate_object_types


def _object_type(id_field="widget_id", title_field=None, fields=None, security=None):
    type_def = {
        "id_field": id_field,
        "fields": fields or {"name": {"type": "data"}},
        # A valid default -- "name" is already the default field
        # above, so callers testing ONLY title_field behavior never
        # need to think about security at all, same as before this
        # validation existed.
        "security": security if security is not None else {"field": "name"},
    }
    if title_field is not None:
        type_def["title_field"] = title_field
    return type_def


# --- title_field ------------------------------------------------------

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


# --- security.field -----------------------------------------------------

def test_security_field_referencing_a_real_data_field_is_valid():
    validate_object_types({"Widget": _object_type(security={"field": "name"})})  # does not raise


def test_security_field_referencing_unknown_field_is_rejected():
    with pytest.raises(ValueError, match="security.field references unknown field"):
        validate_object_types({"Widget": _object_type(security={"field": "totally_fake_field"})})


def test_security_field_referencing_a_link_field_is_rejected():
    fields = {"name": {"type": "data"}, "owner": {"type": "link", "target": "Person"}}
    with pytest.raises(ValueError, match="must be a plain data field"):
        validate_object_types({"Widget": _object_type(fields=fields, security={"field": "owner"})})


# --- security block presence / field-vs-via_field exclusivity -----------

def test_missing_security_block_entirely_is_rejected():
    # Matches core/ontology/mediator.py's own DIRECT, non-.get()
    # access -- a missing block would otherwise raise a raw,
    # uncontrolled KeyError the first time any MAC check ever touched
    # this object type, not a clear error at startup.
    type_def = {"id_field": "widget_id", "fields": {"name": {"type": "data"}}}
    with pytest.raises(ValueError, match="no security block declared"):
        validate_object_types({"Widget": type_def})


def test_security_declaring_both_field_and_via_field_is_rejected():
    fields = {"name": {"type": "data"}, "owner": {"type": "link", "target": "Person"}}
    with pytest.raises(ValueError, match="both 'field' and 'via_field'"):
        validate_object_types(
            {"Widget": _object_type(fields=fields, security={"field": "name", "via_field": "owner"})}
        )


def test_security_declaring_neither_field_nor_via_field_is_rejected():
    with pytest.raises(ValueError, match="neither 'field' nor 'via_field'"):
        validate_object_types({"Widget": _object_type(security={})})


# --- security.via_field --------------------------------------------------

def test_security_via_field_chain_terminating_in_a_real_security_field_is_valid():
    object_types = {
        "Transaction": _object_type(
            fields={"customer_id": {"type": "link", "target": "Customer"}},
            security={"via_field": "customer_id"},
        ),
        "Customer": _object_type(security={"field": "name"}),
    }
    validate_object_types(object_types)  # does not raise


def test_security_via_field_chain_through_multiple_hops_is_valid():
    object_types = {
        "LineItem": _object_type(
            fields={"order_id": {"type": "link", "target": "Order"}},
            security={"via_field": "order_id"},
        ),
        "Order": _object_type(
            fields={"customer_id": {"type": "link", "target": "Customer"}},
            security={"via_field": "customer_id"},
        ),
        "Customer": _object_type(security={"field": "name"}),
    }
    validate_object_types(object_types)  # does not raise


def test_security_via_field_referencing_unknown_field_is_rejected():
    with pytest.raises(ValueError, match="security.via_field references unknown field"):
        validate_object_types({"Widget": _object_type(security={"via_field": "totally_fake_field"})})


def test_security_via_field_referencing_a_data_field_is_rejected():
    # The opposite restriction from security.field -- via_field must
    # be a real link, it's how the chain reaches the next type at all.
    with pytest.raises(ValueError, match="must be a link field"):
        validate_object_types({"Widget": _object_type(security={"via_field": "name"})})


def test_security_via_field_targeting_unknown_object_type_is_rejected():
    fields = {"owner": {"type": "link", "target": "TotallyFakeType"}}
    with pytest.raises(ValueError, match="targets unknown object type"):
        validate_object_types({"Widget": _object_type(fields=fields, security={"via_field": "owner"})})


def test_security_via_field_chain_that_terminates_in_an_invalid_type_is_rejected():
    # The invalid type here is genuinely reached only via the chain --
    # confirms the recursion actually validates the TARGET type's own
    # security, not just that the link itself resolves.
    object_types = {
        "Transaction": _object_type(
            fields={"customer_id": {"type": "link", "target": "Customer"}},
            security={"via_field": "customer_id"},
        ),
        "Customer": _object_type(security={"field": "totally_fake_field"}),
    }
    with pytest.raises(ValueError, match="security.field references unknown field"):
        validate_object_types(object_types)


def test_security_via_field_direct_self_reference_cycle_is_rejected():
    fields = {"self_link": {"type": "link", "target": "Widget"}}
    with pytest.raises(ValueError, match="Circular security.via_field chain"):
        validate_object_types({"Widget": _object_type(fields=fields, security={"via_field": "self_link"})})


def test_security_via_field_two_type_cycle_is_rejected():
    object_types = {
        "A": _object_type(fields={"b_link": {"type": "link", "target": "B"}}, security={"via_field": "b_link"}),
        "B": _object_type(fields={"a_link": {"type": "link", "target": "A"}}, security={"via_field": "a_link"}),
    }
    with pytest.raises(ValueError, match="Circular security.via_field chain"):
        validate_object_types(object_types)


def test_validating_one_type_does_not_leak_visited_state_into_the_next():
    # A real, deliberate design point in _validate_security() -- the
    # `visited` set is passed explicitly per top-level call, never
    # shared/module-level. Two SEPARATE, unrelated via_field chains
    # that happen to pass through the SAME intermediate object type
    # must both validate cleanly -- neither is a cycle relative to the
    # other.
    object_types = {
        "TransactionA": _object_type(
            fields={"customer_id": {"type": "link", "target": "Customer"}},
            security={"via_field": "customer_id"},
        ),
        "TransactionB": _object_type(
            fields={"customer_id": {"type": "link", "target": "Customer"}},
            security={"via_field": "customer_id"},
        ),
        "Customer": _object_type(security={"field": "name"}),
    }
    validate_object_types(object_types)  # does not raise
