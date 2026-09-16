"""
What the lake says about itself.

WHY. A lake in object storage already survives its installation being
deleted -- proved by deleting one and reading its data from elsewhere.
What it cannot do is say what the data MEANS: a fresh Elysium on a
preserved bucket finds tables, rows and provenance, and no ontology to
interpret any of it.

Microsoft's Common Data Model states the goal exactly: self-describing
data in a lake, so "the format of a shared folder helps each consumer
avoid having to 'relearn' the meaning of the data in the lake."

A COPY, NOT A HOME. The configuration is AUTHORED in version control
and LOADED from /etc/elysium. This records what was true when the
tables were written -- the same thing bronze does for rows -- and
nothing reads it in normal operation, so it cannot drift into being a
second source of truth.
"""

import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.manifest import PUBLISHABLE, build_manifest, publish, read_manifests

FILES = {
    "ontology_schema.yaml": "object_types: {}",
    "policy.yaml": "roles: {}",
    "data_silos.yaml": "data_silos: {}",
    "config.yaml": "llm: {model: phi4-mini}",
}


@pytest.fixture
def synced(tmp_path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
    connection.execute("INSERT INTO t VALUES ('1', 'x')")
    connection.commit()
    connection.close()

    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})
    sync.sync_table("s", "t", "id", ["id", "a"], {"id": "string", "a": "string"})
    return sync


class TestWhatIsPublished:
    def test_the_ontology_the_policy_and_the_silos(self, synced):
        manifest = build_manifest(1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])

        assert set(manifest["files"]) == set(PUBLISHABLE)

    def test_the_llm_settings_are_withheld(self, synced):
        """THEY DESCRIBE THE APPLICATION, NOT THE DATA.

        A second Elysium on the same lake might reasonably use a
        different model, so publishing ours would be describing a
        choice rather than a fact about the tables.
        """
        manifest = build_manifest(1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])

        assert "config.yaml" not in manifest["files"]
        assert "config.yaml" in manifest["withheld"]

    def test_withholding_is_named_rather_than_silent(self, synced):
        # A reader finding three files where the deployment had four
        # should be told that was deliberate.
        manifest = build_manifest(1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])

        assert manifest["withheld"] == ["config.yaml"]

    def test_an_unknown_file_is_withheld_by_default(self, synced):
        """AN ALLOW-LIST, NOT AN EXCLUSION LIST, and this is the test
        that proves which.

        An exclusion list fails open the day someone adds a file to the
        config directory -- and the file they add will be the one with
        the credentials in it.
        """
        manifest = build_manifest(
            1, "2026-01-01T00:00:00Z", "d1",
            {**FILES, "secrets_backup.yaml": "password: hunter2"}, ["s.t"],
        )

        assert "secrets_backup.yaml" not in manifest["files"]
        assert "hunter2" not in str(manifest["files"])

    def test_it_names_the_tables_it_describes(self, synced):
        # So a reader can tell whether the manifest still matches what
        # the catalog holds -- a mismatch that cannot be detected from
        # the configuration alone.
        manifest = build_manifest(1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t", "bronze_s.t"])

        assert manifest["tables"] == ["bronze_s.t", "s.t"]

    def test_it_carries_the_digest_of_the_whole_configuration(self, synced):
        # Including the parts NOT published, so two manifests from
        # different configurations are distinguishable even when their
        # published files match.
        manifest = build_manifest(1, "2026-01-01T00:00:00Z", "abc123", FILES, ["s.t"])

        assert manifest["source_digest"] == "abc123"

    def test_it_says_which_shape_it_is(self, synced):
        # The first thing a future reader needs is to know whether it
        # understands what it is holding.
        manifest = build_manifest(1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])

        assert manifest["manifest_version"] == 1


class TestTheRoundTrip:
    def test_a_manifest_can_be_written_and_read_back(self, synced):
        publish(synced._catalog, 7, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])

        found = read_manifests(synced._catalog)

        assert len(found) == 1
        assert found[0]["generation"] == 7

    def test_it_lands_beside_the_data(self, synced):
        # IN STORAGE rather than in the catalog, so it survives catalog
        # loss -- which is precisely when someone most needs to know
        # what the tables were.
        location = publish(synced._catalog, 7, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])

        assert location is not None
        assert "_elysium/manifest-7.json" in location

    def test_generations_do_not_overwrite_each_other(self, synced):
        """ONE PER GENERATION, because "what was the ontology when this
        snapshot was written" is the question this exists to answer and
        a single current file cannot answer it."""
        publish(synced._catalog, 1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])
        publish(synced._catalog, 2, "2026-01-02T00:00:00Z", "d2", FILES, ["s.t"])

        found = read_manifests(synced._catalog)

        assert [m["generation"] for m in found] == [2, 1]

    def test_a_lake_with_no_manifest_reads_as_empty(self, synced):
        # THE CONTROL, and an ordinary state: every lake written before
        # this existed has none, and that must not be an error.
        assert read_manifests(synced._catalog) == []

    def test_gaps_between_generations_are_tolerated(self, synced):
        # Manifests are written when configuration CHANGES, so
        # generations 1 and 5 may exist while 2 to 4 do not.
        publish(synced._catalog, 1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])
        publish(synced._catalog, 5, "2026-01-05T00:00:00Z", "d5", FILES, ["s.t"])

        found = read_manifests(synced._catalog)

        assert [m["generation"] for m in found] == [5, 1]
