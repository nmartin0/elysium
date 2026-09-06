"""
Point 10: display metadata on object types and fields.

FOUNDRY'S PRECEDENT, matched deliberately. Their object type metadata
is displayName, pluralDisplayName, and description; their property
metadata is displayName and description. Elysium had NONE of it -- an
object type carried six keys, all structural, and a field carried
exactly one (`type`). A UI could only ever render raw identifiers:
"owner_customer_id" rather than "Account Owner".

EVERYTHING IS OPTIONAL, and every ontology predating this stays valid.
humanize() supplies a readable fallback, so a UI never has to decide
what to show for an unlabelled field -- which is the point. Requiring
every deployment to label every field before its UI is usable would
make the feature a burden rather than a convenience.
"""

import pytest

from core.ontology.object_type_validation import validate_object_types
from core.ontology.schema import get_display_name, get_plural_display_name, humanize


def test_humanize_turns_identifiers_into_labels():
    assert humanize("transaction_date") == "Transaction Date"
    assert humanize("name") == "Name"
    assert humanize("risk_score") == "Risk Score"


def test_humanize_drops_a_trailing_id_suffix():
    # `_id` names the STORAGE mechanism, not the thing a reader cares
    # about -- a link field reads better as "Owner Customer" than
    # "Owner Customer Id".
    assert humanize("owner_customer_id") == "Owner Customer"
    assert humanize("customer_id") == "Customer"


def test_humanize_leaves_a_bare_id_alone():
    # Dropping the suffix here would leave an empty string.
    assert humanize("id") == "Id"


def test_a_declared_display_name_always_wins():
    assert get_display_name({"display_name": "Account Owner"}, "owner_customer_id") == "Account Owner"


def test_an_undeclared_display_name_falls_back_to_humanized():
    assert get_display_name({}, "owner_customer_id") == "Owner Customer"


def test_plurals_fall_back_naively_and_declared_wins():
    # Deliberately naive: this is a fallback, and a deployment with an
    # irregular plural declares it. Guessing harder would be
    # confidently wrong for exactly the cases that need declaring.
    assert get_plural_display_name({}, "Customer") == "Customers"
    assert get_plural_display_name({"plural_display_name": "People"}, "Person") == "People"


def _schema(**type_extras):
    return {
        "Widget": {
            "storage": {"silo": "primary", "table": "widgets", "id_column": "widget_id"},
            "id_field": "widget_id",
            "security": {"field": "region"},
            "fields": {"region": {"type": "data"}},
            **type_extras,
        }
    }


def test_an_ontology_declaring_no_display_metadata_is_valid():
    validate_object_types(_schema())


def test_declared_display_metadata_validates():
    validate_object_types(
        _schema(display_name="Widget", plural_display_name="Widgets", description="A thing.")
    )


@pytest.mark.parametrize("key", ["display_name", "plural_display_name", "description"])
def test_an_empty_display_value_is_rejected(key):
    # Worse than declaring nothing: an empty string renders as blank in
    # a UI rather than falling back to something readable.
    with pytest.raises(ValueError, match="non-empty string"):
        validate_object_types(_schema(**{key: "   "}))


def test_a_non_string_display_value_is_rejected():
    with pytest.raises(ValueError, match="non-empty string"):
        validate_object_types(_schema(display_name=42))


def test_an_empty_field_display_name_is_rejected():
    schema = _schema()
    schema["Widget"]["fields"]["region"]["display_name"] = ""

    with pytest.raises(ValueError, match="non-empty string"):
        validate_object_types(schema)
