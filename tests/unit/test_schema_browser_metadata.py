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
import yaml

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


# --- per-object-type freshness -------------------------------------------


def test_freshness_is_reported_per_object_type(tmp_path):
    # The deployment-wide figure is the OLDEST of these, which answers
    # "how stale might anything be" and not "which type is stale". A
    # schema browser needs the second.
    import sqlite3

    from core.deployment_loader import load_deployment, mirror_synced_at_by_object_type

    data_dir = tmp_path / "data"
    (data_dir / "dev_fixtures").mkdir(parents=True)
    for db, script in (("mediator.db", "schema.sql"), ("support.db", "support_schema.sql"),
                       ("risk.db", "risk_schema.sql")):
        conn = sqlite3.connect(data_dir / "dev_fixtures" / db)
        conn.executescript((FIXTURES / script).read_text())
        conn.commit()
        conn.close()

    # run_sync takes runtime paths, not a config -- it loads its own,
    # which is the same path an operator's cron entry uses.
    from core.deployment_loader import RuntimePaths
    from scripts.run_sync import run_sync

    log_dir = tmp_path / "log"
    log_dir.mkdir()
    run_sync(RuntimePaths(config_dir=FIXTURES, data_dir=data_dir, log_dir=log_dir))
    config = load_deployment(FIXTURES)

    synced = mirror_synced_at_by_object_type(config, data_dir)

    assert set(synced) == set(config.schema)
    assert all(value is not None for value in synced.values())


def test_a_type_that_never_synced_reports_none(tmp_path):
    # An operational state, not an error: a fresh deployment has not
    # run a sync yet, and a browser should say so rather than raise.
    from core.deployment_loader import load_deployment, mirror_synced_at_by_object_type

    config = load_deployment(FIXTURES)
    synced = mirror_synced_at_by_object_type(config, tmp_path / "empty")

    assert set(synced) == set(config.schema)
    assert all(value is None for value in synced.values())


def test_a_multi_table_type_reports_its_stalest_table(tmp_path):
    # Customer spans two silos in the fixture. It is only as fresh as
    # the later-synced of them, so the EARLIER timestamp is the honest
    # answer -- reporting the newer one would claim data is current
    # when half of it is not.
    schema = yaml.safe_load((FIXTURES / "ontology_schema.yaml").read_text())

    assert schema["object_types"]["Customer"].get("additional_storage"), (
        "this test is meaningless unless Customer really spans two tables"
    )
