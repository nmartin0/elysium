"""
security.via_field must be a FORWARD link (001's F-19).

MEASURED BEFORE: a reverse link was accepted at load, and every read of
that object type then failed with "Could not find column" -- an object
type nobody could read, discovered one request at a time.

A security chain reads a value stored ON the row and follows it. A
reverse link (cardinality "many", resolved through via_table) is
computed by querying the OTHER table: there is nothing here to follow.
core/ontology/schema.py already refused reverse links as SEARCH keys
for the same reason; the rule now lives in one place, link_types, and
both callers use it.
"""

import pytest

from core.ontology.link_types import is_forward_link, is_reverse_link
from core.ontology.object_type_validation import validate_object_types

FORWARD = {"type": "link", "target": "Customer", "cardinality": "one"}
REVERSE = {"type": "link", "target": "Transaction", "cardinality": "many", "via_table": "transactions"}


def _types(customer_security, transaction_security=None):
    return {
        "Customer": {
            "id_field": "customer_id",
            "security": customer_security,
            "fields": {
                "customer_id": {"type": "data"},
                "region": {"type": "data"},
                "transactions": dict(REVERSE),
            },
        },
        "Transaction": {
            "id_field": "transaction_id",
            "security": transaction_security or {"field": "category"},
            "fields": {
                "transaction_id": {"type": "data"},
                "category": {"type": "data"},
                "customer_id": dict(FORWARD),
            },
        },
    }


class TestTheRule:
    def test_a_forward_link_is_one(self):
        assert is_forward_link(FORWARD) and not is_reverse_link(FORWARD)

    def test_a_reverse_link_is_not(self):
        assert is_reverse_link(REVERSE) and not is_forward_link(REVERSE)

    def test_cardinality_many_alone_is_reverse(self):
        assert is_reverse_link({"type": "link", "target": "T", "cardinality": "many"})

    def test_a_via_table_alone_is_reverse(self):
        assert is_reverse_link({"type": "link", "target": "T", "via_table": "t"})

    def test_a_link_that_declares_neither_is_FORWARD(self):
        """CARDINALITY IS OPTIONAL. Requiring an explicit "one" rejected
        valid deployments -- found by the tests it broke, not by me."""
        assert is_forward_link({"type": "link", "target": "Customer"})

    def test_plain_data_is_neither(self):
        assert not is_forward_link({"type": "data"}) and not is_reverse_link({"type": "data"})


class TestValidation:
    def test_a_reverse_link_as_the_security_chain_is_refused(self):
        with pytest.raises(ValueError, match="reverse link"):
            validate_object_types(_types({"via_field": "transactions"}))

    def test_the_message_says_what_to_use_instead(self):
        with pytest.raises(ValueError, match="forward link on 'Transaction'"):
            validate_object_types(_types({"via_field": "transactions"}))

    def test_a_forward_link_chain_still_loads(self):
        """The shipped deployment's own shape: Transaction reaches
        Customer through customer_id, a forward link."""
        validate_object_types(_types({"field": "region"}, {"via_field": "customer_id"}))

    def test_a_plain_security_field_still_loads(self):
        validate_object_types(_types({"field": "region"}))
