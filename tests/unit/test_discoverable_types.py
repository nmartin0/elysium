"""A type listed to everyone by its owner: `discoverable: true`.

It is `discover:{type}` given to every role and nothing more -- the name,
no ids, no search, no fields unless granted. The default is no, so every
existing deployment behaves as before.
"""

import pytest

from core.intermediate_layer.auth import UserRecord
from core.ontology.mediator import DataMediator
from core.ontology.object_type_validation import validate_object_types
from core.ontology.schema import is_discoverable


def _schema(**customer):
    return {
        "Customer": {
            "id_field": "cid", "storage": {"silo": "s", "table": "c", "id_column": "cid"},
            "security": {"field": "name"},
            "fields": {"name": {"type": "data"}, "txns": {"type": "link", "target": "Txn", "cardinality": "many"}},
            **customer,
        },
        "Txn": {
            "id_field": "tid", "storage": {"silo": "s", "table": "t", "id_column": "tid"},
            "security": {"via_field": "customer"},
            "fields": {
                "amount": {"type": "data"},
                "customer": {"type": "link", "target": "Customer", "cardinality": "one", "column": "cust"},
            },
        },
    }


CLERK = {"clerk": {"allowed_actions": frozenset(["read:Txn", "read:Txn.amount", "read:Txn.customer"])}}
PERSON = UserRecord("u", None, "clerk")


def _view(schema, roles=CLERK):
    return DataMediator(schema, {}, {}, roles).visible_schema(PERSON)


def test_the_default_is_hidden():
    assert "Customer" not in _view(_schema())


def test_discoverable_is_exactly_true_and_nothing_loosely_true():
    assert is_discoverable({"discoverable": True}) is True
    assert is_discoverable({}) is False
    assert is_discoverable({"discoverable": False}) is False
    # The one that matters: a quoted "false" is truthy in Python.
    assert is_discoverable({"discoverable": "false"}) is False
    assert is_discoverable({"discoverable": 1}) is False


def test_a_listed_type_is_a_name_and_nothing_else():
    listed = _view(_schema(discoverable=True))["Customer"]

    assert listed["readable"] is False
    assert listed["fields"] == {}
    assert listed["id_field"] is None and listed["title_field"] is None
    assert listed["display_name"] == "Customer"


def test_a_listed_type_is_not_readable_for_the_agent():
    # The model's schema is a menu of what it can DO; a type it cannot
    # search is an item it can only fail on.
    mediator = DataMediator(_schema(discoverable=True), {}, {}, CLERK)

    assert "Customer" not in mediator.visible_schema(PERSON, for_agent=True)


def test_a_field_is_still_only_known_by_its_own_grant():
    # Listing the type does not list its fields: discover:Customer.name
    # is a separate, per-field decision.
    roles = {"clerk": {"allowed_actions": frozenset(["discover:Customer.name"])}}

    fields = _view(_schema(discoverable=True), roles)["Customer"]["fields"]

    assert list(fields) == ["name"] and fields["name"]["readable"] is False


def test_listing_one_type_does_not_list_another():
    view = _view(_schema(discoverable=True))

    assert "Txn" in view          # granted
    roles = {"clerk": {"allowed_actions": frozenset()}}
    assert list(_view(_schema(discoverable=True), roles)) == ["Customer"]


class TestALinkNamesItsTarget:
    """count_links' docstring has always said a link to a type the caller
    is not told about must not be named. The schema served did it anyway."""

    def test_a_forward_link_to_an_unknown_type_becomes_plain_data(self):
        field = _view(_schema())["Txn"]["fields"]["customer"]

        assert field["type"] == "data"
        assert "target" not in field and "cardinality" not in field

    def test_the_value_it_held_is_still_readable(self):
        # Only the relationship is withheld: the id is the person's own
        # data, in a field they were granted.
        assert _view(_schema())["Txn"]["fields"]["customer"]["readable"] is True

    def test_a_reverse_link_to_an_unknown_type_goes_altogether(self):
        roles = {"clerk": {"allowed_actions": frozenset([
            "read:Customer", "read:Customer.name", "read:Customer.txns"])}}

        assert "txns" not in _view(_schema(), roles)["Customer"]["fields"]

    def test_a_link_to_a_listed_type_keeps_its_target(self):
        field = _view(_schema(discoverable=True))["Txn"]["fields"]["customer"]

        assert field["type"] == "link" and field["target"] == "Customer"

    def test_a_link_to_a_type_they_can_discover_by_grant_keeps_its_target(self):
        roles = {"clerk": {"allowed_actions": frozenset([
            "read:Txn", "read:Txn.customer", "discover:Customer"])}}

        assert _view(_schema(), roles)["Txn"]["fields"]["customer"]["target"] == "Customer"


class TestValidation:
    def test_true_and_false_load(self):
        validate_object_types(_schema(discoverable=True))
        validate_object_types(_schema(discoverable=False))

    @pytest.mark.parametrize("value", ["false", "yes", 1, 0, []])
    def test_anything_but_a_boolean_is_refused_with_the_value_shown(self, value):
        with pytest.raises(ValueError, match="discoverable must be true or false"):
            validate_object_types(_schema(discoverable=value))
