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


# --- Action parameters ---------------------------------------------------
#
# Object types and fields gained display metadata earlier; action
# parameters did not, which left it missing from the one place it
# matters most. A parameter is what a person is asked to fill in and
# what the model is asked to supply, and "new_from_balance (number,
# required)" tells neither of them whether that is the resulting
# balance or the amount to move.


def _action(**param_extras):
    return {
        "Transfer": {
            "affected_object_types": ["Widget"],
            "parameters": {
                "widget_id": {
                    "type": "object_reference", "object_type": "Widget", **param_extras
                }
            },
            "sub_writes": [
                {
                    "object_type": "Widget", "object_id": "parameter.widget_id",
                    "operation": "update",
                    "mutations": [{"set": {"property": "region", "value": "x"}}],
                }
            ],
        }
    }


def test_an_action_parameter_may_declare_display_metadata():
    from core.ontology.action_types import validate_action_types

    validate_action_types(
        _action(display_name="Widget", description="Which widget to move."),
        {
            "Widget": {
                "storage": {"silo": "p", "table": "w", "id_column": "widget_id"},
                "id_field": "widget_id",
                "fields": {"region": {"type": "data"}},
            }
        },
    )


@pytest.mark.parametrize("key", ["display_name", "description"])
def test_an_empty_parameter_display_value_is_rejected(key):
    # Same rule as object types and fields: an empty label renders
    # blank rather than falling back to something readable.
    from core.ontology.action_types import validate_action_types

    with pytest.raises(ValueError, match="non-empty string"):
        validate_action_types(
            _action(**{key: "  "}),
            {
                "Widget": {
                    "storage": {"silo": "p", "table": "w", "id_column": "widget_id"},
                    "id_field": "widget_id",
                    "fields": {"region": {"type": "data"}},
                }
            },
        )


def test_a_parameter_description_reaches_the_agents_prompt():
    # THE reason this gap mattered. The model has to supply the value,
    # and the type alone does not say what the value means.
    from core.llm.agent_step_prompt import _describe_actions

    described = _describe_actions(
        {
            "TransferFunds": {
                "affected_object_types": ["Account"],
                "parameters": {
                    "new_from_balance": {
                        "type": "number", "required": True,
                        "description": "the balance the source should END with",
                    }
                },
                "sub_writes": [
                    {"object_type": "Account", "object_id": "$x", "operation": "update"}
                ],
                "executable": True,
            }
        },
        [],
    )

    assert "the balance the source should END with" in described


def test_a_parameter_without_a_description_is_described_as_before():
    # The addition must not change how an undeclared parameter reads --
    # every existing deployment has none.
    from core.llm.agent_step_prompt import _describe_actions

    described = _describe_actions(
        {
            "Plain": {
                "affected_object_types": ["Account"],
                "parameters": {"amount": {"type": "number", "required": True}},
                "sub_writes": [
                    {"object_type": "Account", "object_id": "$x", "operation": "update"}
                ],
                "executable": True,
            }
        },
        [],
    )

    assert "amount (number, required)" in described
    assert "--" not in described.split("\n")[0]
