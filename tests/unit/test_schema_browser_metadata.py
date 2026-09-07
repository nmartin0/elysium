"""
The two backend additions the schema browser needs: a `group` label on
object types, and per-object-type mirror freshness.

Both are display concerns, and both are additions to
visible_schema()'s shape -- which is why they come before the UI that
renders it rather than after. Adding them later would mean rewriting
whatever consumed the earlier shape.
"""

from pathlib import Path

import pytest

from core.ontology.object_type_validation import validate_object_types

FIXTURES = Path("tests/integration/fixtures")


def _schema(**extras):
    return {
        "Widget": {
            "storage": {"silo": "primary", "table": "widgets", "id_column": "widget_id"},
            "id_field": "widget_id",
            "security": {"field": "region"},
            "fields": {"region": {"type": "data"}},
            **extras,
        }
    }


# --- group ---------------------------------------------------------------


def test_a_group_label_validates():
    validate_object_types(_schema(group="Finance"))


def test_no_group_is_fine():
    # Optional, like every other piece of display metadata. An ontology
    # predating this stays valid.
    validate_object_types(_schema())


@pytest.mark.parametrize("bad", ["", "   ", 42])
def test_an_empty_or_non_string_group_is_rejected(bad):
    # Same rule as display_name: an empty label renders blank rather
    # than falling back to something readable.
    with pytest.raises(ValueError, match="non-empty string"):
        validate_object_types(_schema(group=bad))


def test_the_group_reaches_visible_schema():
    from core.intermediate_layer.auth import UserRecord
    from core.ontology.mediator import DataMediator

    schema = _schema(group="Finance")
    mediator = DataMediator(
        schema, {}, {"Widget": "primary"},
        {"r": {"allowed_actions": ["read:Widget", "read:Widget.region"]}},
    )
    user = UserRecord(user_id="u", security_value="us-west", role_name="r")

    assert mediator.visible_schema(user)["Widget"]["group"] == "Finance"


# Per-object-type mirror freshness was built here and REMOVED. It was
# reachable from no route and read by no screen -- I justified it as
# something the schema browser needed, then built the schema browser
# without it.
#
# Worse than merely unused: no shipped deployment sets
# read_from_mirror, so every type would have reported "never synced"
# for data that is in fact current. Wiring it would have been
# misleading rather than incomplete.
#
# Reinstate when a deployment actually reads from the mirror. The
# deployment-wide figure on /data-freshness already covers the case
# that exists today.
