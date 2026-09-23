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

import dataclasses
import shutil

import pytest

from core.deployment_loader import RuntimePaths, build_generation
from scripts.run_sync import run_sync


@pytest.fixture
def deployment(tmp_path, synced_deployment):
    """A synced deployment. THE SWITCH IS GONE (GOLD-8): reads come
    from gold and from nothing else, so there is no longer a
    mirror-reading variant to compare against."""
    def build():
        config_dir = tmp_path / "etc"
        shutil.copytree(synced_deployment.config_dir, config_dir)
        data_dir = tmp_path / "data"
        log_dir = tmp_path / "log"
        shutil.copytree(synced_deployment.data_dir, data_dir)
        log_dir.mkdir()
        run_sync(RuntimePaths(config_dir=config_dir, data_dir=data_dir, log_dir=log_dir))
        return build_generation(config_dir, data_dir, log_dir)
    return build


class TestWhatTheGenerationKnows:
    def test_reading_gold_records_when_each_type_was_published(self, deployment):
        generation = deployment()

        assert sorted(generation.gold_published_at) == ["Customer", "Transaction"]

    def test_every_type_reports_a_publication(self, deployment):
        """There is no mirror-reading variant left to report nothing:
        a type without a publication cannot be served at all."""
        generation = deployment()

        assert sorted(generation.gold_published_at) == ["Customer", "Transaction"]

    def test_the_publication_is_LATER_than_the_source_read(self, deployment):
        """The whole reason the two are reported separately."""
        generation = deployment()

        assert all(published > generation.mediator.mirror_synced_at
                   for published in generation.gold_published_at.values())

    def test_the_overlay_is_still_bounded_by_the_SOURCE_read(self, deployment):
        """F-29's window. If this ever became the publication time,
        writes applied between the read and the publication would be in
        neither the mirror nor the overlay."""
        generation = deployment()

        assert generation.mediator.mirror_synced_at is not None
        assert generation.mediator.mirror_synced_at <= min(
            generation.gold_published_at.values())


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
        answer = self._freshness(deployment())

        assert answer["source"] == "gold" and answer["published_at"]

    def test_it_names_the_mirror_only_when_nothing_is_published(self, deployment):
        """The branch is kept because a deployment that has not synced
        still answers /api/data-freshness -- it just cannot serve
        reads."""
        generation = deployment()
        stripped = dataclasses.replace(generation, gold_published_at={})

        answer = self._freshness(stripped)

        assert answer["source"] == "mirror" and "published_at" not in answer

    def test_and_carries_BOTH_clocks_when_reading_gold(self, deployment):
        answer = self._freshness(deployment())

        assert answer["last_synced_at"] is not None
        assert min(answer["published_at"].values()) >= answer["last_synced_at"]
