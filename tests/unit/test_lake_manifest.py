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


class TestAuditFindings:
    """Behaviours an audit of this module added, each for a real gap.

    Grouped rather than scattered so the reason they exist stays
    visible: none was in the original design, and each came from
    comparing this file against the project's own recorded positions.
    """

    def test_a_corrupt_manifest_is_reported_not_skipped(self, synced, caplog):
        """PRESENT BUT UNREADABLE IS NOT THE SAME AS ABSENT.

        The read loop counted a parse failure as a missing generation,
        so a damaged manifest made the lake look undescribed rather
        than damaged -- and a damaged one is the file someone would
        reach for during an incident.
        """
        from core.mirror.manifest import MANIFEST_PREFIX, _file_io, _warehouse_root

        publish(synced._catalog, 1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])
        location = f"{_warehouse_root(synced._catalog)}/{MANIFEST_PREFIX}/manifest-2.json"
        with _file_io(synced._catalog).new_output(location).create(overwrite=True) as stream:
            stream.write(b"{ this is not json")

        found = read_manifests(synced._catalog)

        assert [m["generation"] for m in found] == [1]
        assert any("could not be parsed" in record.message for record in caplog.records)

    def test_a_corrupt_manifest_does_not_hide_later_ones(self, synced):
        # Counted as a MISS, a corrupt file at generation 2 would
        # contribute to the run of absences that ends the search --
        # so a readable generation 3 could be lost behind a damaged 2.
        from core.mirror.manifest import MANIFEST_PREFIX, _file_io, _warehouse_root

        publish(synced._catalog, 1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"])
        location = f"{_warehouse_root(synced._catalog)}/{MANIFEST_PREFIX}/manifest-2.json"
        with _file_io(synced._catalog).new_output(location).create(overwrite=True) as stream:
            stream.write(b"not json")
        publish(synced._catalog, 3, "2026-01-03T00:00:00Z", "d3", FILES, ["s.t"])

        found = read_manifests(synced._catalog)

        assert [m["generation"] for m in found] == [3, 1]

    def test_publishing_to_an_impossible_location_warns_and_returns_none(
        self, synced, caplog,
    ):
        """NAMED EXCEPTIONS, NOT `except Exception`.

        A bare catch here turned a misremembered method name into a
        warning about the manifest rather than the AttributeError it
        was -- the same mistake iceberg_sync.py records having made
        with a bare catch that "swallowed every real failure too".
        """
        broken = type("NoWarehouse", (), {"properties": {}})()

        assert publish(broken, 1, "2026-01-01T00:00:00Z", "d1", FILES, ["s.t"]) is None
        assert any("not published" in record.message for record in caplog.records)
