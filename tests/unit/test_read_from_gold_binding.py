"""
Binding reads to gold, per object type (GOLD-3).

The wiring, and deliberately the whole of it: which schema and which
adapters DataMediator holds. No branch is threaded through any read
path -- the connector satisfies what the mediator asks, and the gold
view is a schema like any other.

PER TYPE, NOT ALL-OR-NOTHING. Gold does not build every type yet (one
with several sources waits for GOLD-5) and a type may simply not have
been published. Either way that type keeps the binding it had, so a
deployment is never asked to choose between all of gold and none.

OFF BY DEFAULT while this is proven, and off must mean TODAY'S
BEHAVIOUR EXACTLY.
"""

import shutil
from typing import NamedTuple

import pytest
import yaml

from core.deployment_loader import RuntimePaths, build_generation, load_deployment
from core.intermediate_layer.auth import UserRecord
from core.mirror.gold_connector import GoldConnector
from scripts.run_sync import run_sync

DEBUG = UserRecord("debug", "us-west", "debug")


class Built(NamedTuple):
    """A built generation, and the paths it was built from -- which a
    test needs to rebuild after changing the lake underneath."""

    generation: object
    paths: RuntimePaths


@pytest.fixture
def deployment(tmp_path, synced_deployment):
    """The shipped deployment, synced, with gold built -- and a switch."""
    def build(read_from_gold: bool, schema_edit=None):
        config_dir = tmp_path / f"etc-{read_from_gold}-{bool(schema_edit)}"
        shutil.copytree(synced_deployment.config_dir, config_dir)
        config = yaml.safe_load((config_dir / "config.yaml").read_text())
        config["mirror"] = {**(config.get("mirror") or {}), "read_from_gold": read_from_gold}
        (config_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
        if schema_edit is not None:
            schema = yaml.safe_load((config_dir / "ontology_schema.yaml").read_text())
            schema_edit(schema.get("object_types", schema))
            (config_dir / "ontology_schema.yaml").write_text(yaml.safe_dump(schema, sort_keys=False))
        data_dir = tmp_path / f"data-{read_from_gold}-{bool(schema_edit)}"
        log_dir = tmp_path / f"log-{read_from_gold}-{bool(schema_edit)}"
        shutil.copytree(synced_deployment.data_dir, data_dir)
        log_dir.mkdir()
        paths = RuntimePaths(config_dir=config_dir, data_dir=data_dir, log_dir=log_dir)
        run_sync(paths)   # fills silver AND builds gold
        return Built(build_generation(config_dir, data_dir, log_dir), paths)
    return build


class TestTheSwitch:
    def test_off_binds_nothing_to_gold(self, deployment):
        generation, _ = deployment(read_from_gold=False)

        assert "gold" not in set(generation.mediator.silo_for_type.values())

    def test_on_binds_the_types_gold_publishes(self, deployment):
        generation, _ = deployment(read_from_gold=True)

        assert generation.mediator.silo_for_type["Customer"] == "gold"
        assert generation.mediator.silo_for_type["Transaction"] == "gold"

    def test_the_default_is_off(self, synced_deployment):
        """A deployment that says nothing keeps today's behaviour."""
        assert load_deployment(synced_deployment.config_dir).read_from_gold is False

    def test_on_uses_the_connector_not_an_adapter(self, deployment):
        generation, _ = deployment(read_from_gold=True)

        assert isinstance(generation.mediator.adapters["gold"], GoldConnector)


class TestTheReadsThemselves:
    def test_the_same_objects_come_back(self, deployment):
        from_source, _ = deployment(read_from_gold=False)
        from_gold, _ = deployment(read_from_gold=True)

        assert (sorted(from_source.mediator.search_object(DEBUG, "Customer", []))
                == sorted(from_gold.mediator.search_object(DEBUG, "Customer", [])))

    def test_and_the_same_fields(self, deployment):
        from_source, _ = deployment(read_from_gold=False)
        from_gold, _ = deployment(read_from_gold=True)

        assert (from_source.mediator.get_object(DEBUG, "Customer", "cust_001", ["name", "region"])
                == from_gold.mediator.get_object(DEBUG, "Customer", "cust_001", ["name", "region"]))

    def test_links_are_followed_through_gold(self, deployment):
        from_source, _ = deployment(read_from_gold=False)
        from_gold, _ = deployment(read_from_gold=True)

        assert (sorted(from_source.mediator.search_around(DEBUG, "Customer", [], "transactions"))
                == sorted(from_gold.mediator.search_around(DEBUG, "Customer", [], "transactions")))


class TestWhatStaysOnTheSource:
    def test_a_type_gold_cannot_build_keeps_its_old_binding(self, deployment):
        """A type spanning several sources waits for GOLD-5 -- and must
        keep being served meanwhile, not disappear."""
        def spread_customer(types):
            types["Customer"]["additional_storage"] = {
                "extra": {"silo": "primary_sql", "table": "customers",
                           "id_column": "customer_id"},
            }

        generation, _ = deployment(read_from_gold=True, schema_edit=spread_customer)

        assert generation.mediator.silo_for_type["Customer"] != "gold"
        assert generation.mediator.search_object(DEBUG, "Customer", [])

    def test_and_so_does_anything_linking_to_it(self, deployment):
        """The gold view excludes those too, because a link into a type
        with no gold table cannot be followed there."""
        def spread_customer(types):
            types["Customer"]["additional_storage"] = {
                "extra": {"silo": "primary_sql", "table": "customers",
                           "id_column": "customer_id"},
            }

        generation, _ = deployment(read_from_gold=True, schema_edit=spread_customer)

        assert generation.mediator.silo_for_type["Transaction"] != "gold"


class TestAMixedDeployment:
    """SOME types on gold, others on the source, in one deployment.

    WRITTEN BECAUSE TWO CONTROLS PROVED NOTHING. The earlier tests
    make EVERY type fall back -- Customer is excluded and Transaction
    links to it -- so the binding returns early and never builds a
    mixed map. Mutating the per-type logic changed nothing observable
    until these existed.
    """

    @staticmethod
    def _add_a_standalone_multi_source_type(types):
        types["Note"] = {
            "id_field": "note_id",
            "security": {"field": "region"},
            "storage": {"silo": "primary_sql", "table": "customers",
                         "id_column": "customer_id"},
            "additional_storage": {"extra": {"silo": "primary_sql", "table": "customers",
                                              "id_column": "customer_id"}},
            "fields": {"note_id": {"type": "data", "column": "customer_id"},
                        "region": {"type": "data"}},
        }

    def test_the_buildable_types_go_to_gold(self, deployment):
        generation, _ = deployment(read_from_gold=True,
                                 schema_edit=self._add_a_standalone_multi_source_type)

        assert generation.mediator.silo_for_type["Customer"] == "gold"
        assert generation.mediator.silo_for_type["Transaction"] == "gold"

    def test_and_the_one_gold_cannot_build_stays_on_its_source(self, deployment):
        generation, _ = deployment(read_from_gold=True,
                                 schema_edit=self._add_a_standalone_multi_source_type)

        assert generation.mediator.silo_for_type["Note"] == "primary_sql"

    def test_the_read_schema_is_mixed_too(self, deployment):
        """Gold's types are described in gold's terms; the others keep
        the source's, because that is where they are read from."""
        generation, _ = deployment(read_from_gold=True,
                                 schema_edit=self._add_a_standalone_multi_source_type)
        schema = generation.mediator.schema

        assert schema["Customer"]["storage"]["table"] == "Customer"
        assert schema["Note"]["storage"]["table"] == "customers"

    def test_a_type_whose_gold_vanished_falls_back_alone(self, deployment):
        """PUBLISHED IS NOT THE SAME AS BUILDABLE. A type the view
        includes but the lake has not published must fall back by
        itself, without taking the others with it."""
        generation, paths = deployment(read_from_gold=True)
        generation.mediator.adapters["gold"]._reader._catalog.drop_table("gold.Transaction")

        rebuilt = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)

        assert rebuilt.mediator.silo_for_type["Customer"] == "gold"
        assert rebuilt.mediator.silo_for_type["Transaction"] == "primary_sql"


class TestThePinning:
    def test_every_bound_type_is_pinned_to_a_published_snapshot(self, deployment):
        """One publication per request: a build finishing mid-request
        must not move the ground under it."""
        generation, _ = deployment(read_from_gold=True)
        connector = generation.mediator.adapters["gold"]

        pinned = connector._reader._snapshot_ids

        assert set(pinned) == {"Customer", "Transaction"}
        assert all(isinstance(snapshot, int) for snapshot in pinned.values())

    def test_the_write_path_still_describes_the_SOURCE(self, deployment):
        """Writes go to the customer's database (D3), so the write
        mediator must not have been rebound."""
        generation, _ = deployment(read_from_gold=True)

        storage = generation.config.schema["Customer"]["storage"]

        assert storage["silo"] == "primary_sql" and storage["table"] == "customers"
