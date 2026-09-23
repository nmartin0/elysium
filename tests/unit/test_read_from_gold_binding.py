"""
Reads come from gold, and from nothing else (GOLD-8).

THE OWNER, September 23: "there's no reason anymore why Elysium
shouldn't be reading from the pristine gold layer, as anything else is
inferior data". So the switch is gone. A mirrored deployment binds
every object type to published gold, and a type that cannot be served
from gold stops the deployment rather than being served from silver.

WHY REFUSING BEATS FALLING BACK. Silver is not a lesser gold: it has
not been conformed to the ontology, its links are not re-keyed, and
its columns carry the source's words rather than the ontology's.
Serving it would answer the same question with worse data and say
nothing about the difference -- and the person reading it would have
no way to tell.

AND THE SYNC IS NOT SERVING. It loads the same bundle in order to
BUILD gold, so it must start when gold does not exist yet. Refusing
there would mean a deployment could never run its first sync, which is
exactly what happened the moment the refusal was written.
"""

import shutil

import pytest
import yaml

from core.deployment_loader import RuntimePaths, build_generation
from core.intermediate_layer.auth import UserRecord
from core.mirror.gold_connector import GoldConnector
from scripts.run_sync import run_sync

DEBUG = UserRecord("debug", "us-west", "debug")


@pytest.fixture
def deployment(tmp_path, synced_deployment):
    """A copy of the shipped deployment, optionally edited, synced."""
    def build(schema_edit=None, sync: bool = True, name: str = "d"):
        config_dir = tmp_path / f"etc-{name}"
        shutil.copytree(synced_deployment.config_dir, config_dir)
        if schema_edit is not None:
            schema = yaml.safe_load((config_dir / "ontology_schema.yaml").read_text())
            schema_edit(schema.get("object_types", schema))
            (config_dir / "ontology_schema.yaml").write_text(
                yaml.safe_dump(schema, sort_keys=False))
        data_dir = tmp_path / f"data-{name}"
        log_dir = tmp_path / f"log-{name}"
        if sync:
            shutil.copytree(synced_deployment.data_dir, data_dir)
        else:
            # A DEPLOYMENT THAT HAS NEVER SYNCED, seeded like the
            # fixture but with no mirror and no gold -- copying the
            # synced one would bring gold with it and prove nothing.
            import scripts.seed_dev_silos as seed
            data_dir.mkdir(parents=True)
            for schema_name, db_name in seed.DATABASES:
                seed.build(seed.FIXTURES / schema_name, data_dir / "dev_fixtures" / db_name)
        log_dir.mkdir()
        paths = RuntimePaths(config_dir=config_dir, data_dir=data_dir, log_dir=log_dir)
        if sync:
            run_sync(paths)
        return paths
    return build


class TestGoldIsTheOnlyPath:
    def test_every_type_is_bound_to_gold(self, deployment):
        paths = deployment()

        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)

        assert set(generation.mediator.silo_for_type.values()) == {"gold"}

    def test_through_the_connector_rather_than_an_adapter(self, deployment):
        paths = deployment()

        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)

        assert isinstance(generation.mediator.adapters["gold"], GoldConnector)

    def test_reads_answer(self, deployment):
        paths = deployment()
        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)

        found = generation.mediator.search_object(DEBUG, "Customer", [])

        assert found
        assert generation.mediator.get_object(
            DEBUG, "Customer", found[0], ["name"])["name"]

    def test_links_are_followed_through_gold(self, deployment):
        paths = deployment()
        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)

        assert generation.mediator.search_around(DEBUG, "Customer", [], "transactions")


class TestWhatStopsTheDeployment:
    def test_gold_not_published_still_serves_NOTHING_from_silver(self, deployment):
        """A deployment that has not synced is not a deployment that
        should serve silver.

        LOUD, NOT FATAL. An API that cannot START until gold exists
        cannot tell anyone why, and a first sync happens after a first
        boot. So the deployment builds, the log says what is missing,
        and a READ of that type raises rather than quietly answering
        from the source."""
        from core.mirror.gold_connector import GoldPublicationMissing
        paths = deployment(sync=False, name="unsynced")

        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir,
                                       serving=True)

        assert generation.mediator.silo_for_type["Customer"] == "gold"
        with pytest.raises(GoldPublicationMissing, match="Run a sync"):
            generation.mediator.search_object(DEBUG, "Customer", [])

    def test_a_type_gold_cannot_build_refuses_and_names_it(self, deployment):
        def break_customer(types):
            del types["Customer"]["id_field"]

        with pytest.raises(Exception, match="Customer|id_field"):
            paths = deployment(schema_edit=break_customer, name="broken")
            build_generation(paths.config_dir, paths.data_dir, paths.log_dir)

    def test_a_vanished_gold_table_fails_LOUDLY_rather_than_falling_back(self, deployment):
        """The case that used to fall back silently for one type."""
        from core.mirror.gold_connector import GoldPublicationMissing
        paths = deployment(name="vanished")
        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)
        generation.mediator.adapters["gold"]._reader._catalog.drop_table("gold.Transaction")

        rebuilt = build_generation(paths.config_dir, paths.data_dir, paths.log_dir,
                                    serving=True)

        assert rebuilt.mediator.silo_for_type["Transaction"] == "gold"
        with pytest.raises(GoldPublicationMissing):
            rebuilt.mediator.search_object(DEBUG, "Transaction", [])


class TestTheSyncStillStarts:
    def test_a_sync_runs_before_gold_exists(self, deployment):
        """THE CIRCULARITY THIS AVOIDS: the sync is what publishes gold,
        so it must load a bundle when none is published. Refusing there
        made the first sync impossible."""
        paths = deployment(sync=False, name="first")

        assert run_sync(paths) == 0

        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)
        assert set(generation.mediator.silo_for_type.values()) == {"gold"}


class TestThePinning:
    def test_every_type_is_pinned_to_its_publication(self, deployment):
        paths = deployment()

        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)

        pinned = generation.mediator.adapters["gold"]._reader._snapshot_ids
        assert set(pinned) == {"Customer", "Transaction"}

    def test_the_write_path_still_describes_the_SOURCE(self, deployment):
        """Writes go to the customer's database (D3), so the write
        mediator must not have been rebound."""
        paths = deployment()

        generation = build_generation(paths.config_dir, paths.data_dir, paths.log_dir)

        storage = generation.config.schema["Customer"]["storage"]
        assert storage["silo"] == "primary_sql" and storage["table"] == "customers"
