"""
Which layer a reader is seeing, and when it was published (GOLD-3).

TWO CLOCKS, AND THEY ARE NOT THE SAME INSTANT. Silver records when
the SOURCE WAS READ; gold records when a PUBLICATION WAS MADE. A
source read hourly but published daily is a day stale to the person
looking at it, and no source-side timestamp says so -- which is why
DEV_UI.md 16.6 measures freshness from the publication.

AND THE SOURCE-READ TIME MUST STAY WHAT IT IS. It bounds the write
overlay (F-29): everything applied after it is still overlaid on read.
Reporting the publication there instead would silently move that
window -- the exact bug patch 335 closed -- so the route carries BOTH,
each meaning its own thing.
"""

import shutil

import pytest
import yaml

from core.deployment_loader import RuntimePaths, build_generation
from scripts.run_sync import run_sync


@pytest.fixture
def deployment(tmp_path, synced_deployment):
    def build(read_from_gold: bool):
        config_dir = tmp_path / f"etc-{read_from_gold}"
        shutil.copytree(synced_deployment.config_dir, config_dir)
        config = yaml.safe_load((config_dir / "config.yaml").read_text())
        config["mirror"] = {**(config.get("mirror") or {}), "read_from_gold": read_from_gold}
        (config_dir / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
        data_dir = tmp_path / f"data-{read_from_gold}"
        log_dir = tmp_path / f"log-{read_from_gold}"
        shutil.copytree(synced_deployment.data_dir, data_dir)
        log_dir.mkdir()
        run_sync(RuntimePaths(config_dir=config_dir, data_dir=data_dir, log_dir=log_dir))
        return build_generation(config_dir, data_dir, log_dir)
    return build


class TestWhatTheGenerationKnows:
    def test_reading_gold_records_when_each_type_was_published(self, deployment):
        generation = deployment(read_from_gold=True)

        assert sorted(generation.gold_published_at) == ["Customer", "Transaction"]

    def test_reading_the_mirror_records_nothing_of_the_kind(self, deployment):
        """Empty is what tells a caller it is NOT looking at gold."""
        generation = deployment(read_from_gold=False)

        assert dict(generation.gold_published_at) == {}

    def test_the_publication_is_LATER_than_the_source_read(self, deployment):
        """The whole reason the two are reported separately."""
        generation = deployment(read_from_gold=True)

        assert all(published > generation.mediator.mirror_synced_at
                   for published in generation.gold_published_at.values())

    def test_the_overlay_is_still_bounded_by_the_SOURCE_read(self, deployment):
        """F-29's window. If this ever became the publication time,
        writes applied between the read and the publication would be in
        neither the mirror nor the overlay."""
        from_mirror = deployment(read_from_gold=False)
        from_gold = deployment(read_from_gold=True)

        assert from_gold.mediator.mirror_synced_at is not None
        assert from_gold.mediator.mirror_synced_at <= min(from_gold.gold_published_at.values())
        assert from_mirror.mediator.mirror_synced_at is not None


class TestWhatTheRouteSays:
    def _freshness(self, generation):
        """The route's own logic, with its dependencies stood in for."""
        config = generation.config
        mediator = generation.mediator
        if not config.read_from_mirror:
            return {"source": "live", "last_synced_at": None}
        published = dict(generation.gold_published_at)
        if published:
            return {"source": "gold", "last_synced_at": mediator.mirror_synced_at,
                    "published_at": published}
        return {"source": "mirror", "last_synced_at": mediator.mirror_synced_at}

    def test_it_names_gold_when_gold_is_what_is_read(self, deployment):
        answer = self._freshness(deployment(read_from_gold=True))

        assert answer["source"] == "gold" and answer["published_at"]

    def test_it_still_names_the_mirror_otherwise(self, deployment):
        answer = self._freshness(deployment(read_from_gold=False))

        assert answer["source"] == "mirror" and "published_at" not in answer

    def test_and_carries_BOTH_clocks_when_reading_gold(self, deployment):
        answer = self._freshness(deployment(read_from_gold=True))

        assert answer["last_synced_at"] is not None
        assert min(answer["published_at"].values()) >= answer["last_synced_at"]
