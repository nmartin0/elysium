"""
Destroy Elysium, keep the lake, stand a fresh one up.

THE REQUIREMENT: tear the system down, preserve the data lake, install
a fresh Elysium on top of it, continue running.

THE ANSWER TODAY IS NO, and this test says so rather than working
around it. What follows measures the gap precisely, because "it
doesn't work" is not actionable and "it fails at these three specific
points" is.

THE BLOCKING DEFECT: an Iceberg lake written by pyiceberg's SqlCatalog
is NOT PORTABLE. Absolute paths are baked in at three depths --

  the catalog row's metadata_location,
  the metadata JSON's own `location` and every `manifest-list`,
  and the manifests' references to their data files.

-- so a lake copied anywhere else fails with FileNotFoundError naming
a directory that no longer exists. A backup restored to a different
path, a container with a different mount, a move between disks: all
break it. Verified at every one of those three depths rather than
inferred from the first.

I SPENT A WHILE WRITING A HELPER TO REWRITE THOSE PATHS before
concluding that a migration tool implemented inside a test is not a
test. The rewriting stops; the measuring starts.

THE SECOND GAP, which would remain even if paths were relative: the
lake holds tables, rows and provenance, and nothing that says what any
of it MEANS. The ontology, the policy and the silo definitions live
outside it -- and by the control-plane standard all three belong in
it.
"""

import shutil
import sqlite3
from pathlib import Path

import pytest
from pyiceberg.catalog.sql import SqlCatalog

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

COLUMNS = ["id", "a"]
TYPES = {"id": "string", "a": "string"}


@pytest.fixture
def lived_in_deployment(tmp_path):
    """A deployment that has run: synced, changed, synced again.

    TWICE, deliberately. One sync leaves no changelog -- there is
    nothing to diff against -- and the changelog is the only thing in
    the lake a re-sync could not rebuild. A teardown test on a
    deployment holding nothing irreplaceable would prove nothing.
    """
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
    connection.executemany("INSERT INTO t VALUES (?, ?)", [("1", "x"), ("2", "y")])
    connection.commit()
    connection.close()

    data_dir = tmp_path / "var"
    mirror_dir = data_dir / "mirror"
    sync = IcebergMirrorSync(mirror_dir, {"s": SQLiteReadAdapter({"path": source})})
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    connection = sqlite3.connect(source)
    connection.execute("UPDATE t SET a = 'CHANGED' WHERE id = '1'")
    connection.commit()
    connection.close()
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    for name in ("write_log.db", "credentials.db", "config_history.db", "metrics.db"):
        (data_dir / name).write_text("pretend state")
    (data_dir / "secrets").mkdir()

    return data_dir, mirror_dir


def _tear_down_keeping_the_lake(data_dir: Path, mirror_dir: Path) -> Path:
    """Destroys everything except the lake, as a reinstall would.

    BY COPYING THE LAKE OUT rather than deleting around it, so the test
    cannot pass because something was missed. What the new install sees
    is exactly what was preserved.
    """
    preserved = data_dir.parent / "preserved"
    preserved.mkdir()
    shutil.copytree(mirror_dir, preserved / "mirror")
    shutil.rmtree(data_dir)
    return preserved


def _catalog_for(mirror_dir: Path) -> SqlCatalog:
    return SqlCatalog(
        "elysium_mirror",
        uri=f"sqlite:///{mirror_dir / 'catalog.db'}",
        warehouse=f"file://{mirror_dir / 'warehouse'}",
    )


class TestTheLakeIsNotPortable:
    """The blocking defect, measured at each depth it occurs.

    Stated as passing tests asserting the FAILURE, so that fixing it
    turns them red. A skipped test or a comment would let the fix land
    without anyone noticing these should change.
    """

    def test_a_moved_lake_cannot_be_read(self, lived_in_deployment):
        data_dir, mirror_dir = lived_in_deployment
        preserved = _tear_down_keeping_the_lake(data_dir, mirror_dir)

        catalog = _catalog_for(preserved / "mirror")

        with pytest.raises(FileNotFoundError):
            catalog.load_table("s.t").scan().to_arrow()

    def test_the_catalog_stores_absolute_paths(self, lived_in_deployment):
        # Depth one: the catalog row.
        data_dir, mirror_dir = lived_in_deployment

        connection = sqlite3.connect(mirror_dir / "catalog.db")
        try:
            locations = [
                row[0] for row in
                connection.execute("SELECT metadata_location FROM iceberg_tables")
            ]
        finally:
            connection.close()

        assert locations
        assert all(location.startswith("file:///") for location in locations)

    def test_the_metadata_json_stores_absolute_paths(self, lived_in_deployment):
        """Depth two, and the reason rewriting the catalog is not
        enough -- a first attempt did exactly that and three tests
        still failed."""
        import json

        data_dir, mirror_dir = lived_in_deployment
        metadata = sorted(
            (mirror_dir / "warehouse" / "s" / "t" / "metadata").glob("*.metadata.json"),
        )[-1]
        body = json.loads(metadata.read_text())

        assert body["location"].startswith("file:///")
        assert body["snapshots"][0]["manifest-list"].startswith("file:///")

    def test_even_rewriting_both_is_not_enough(self, lived_in_deployment):
        """Depth three: the manifests are Avro and hold their own
        absolute references.

        This is the test that settles the approach. Rewriting the
        catalog and the JSON leaves the read still failing, so the fix
        cannot be a path-rewriting migration bolted on afterwards --
        it has to be relative locations at write time, or a catalog
        rebuilt from the warehouse on load.
        """
        data_dir, mirror_dir = lived_in_deployment
        preserved = _tear_down_keeping_the_lake(data_dir, mirror_dir)
        new_mirror = preserved / "mirror"

        old_text, new_text = str(mirror_dir), str(new_mirror)
        connection = sqlite3.connect(new_mirror / "catalog.db")
        try:
            connection.execute(
                "UPDATE iceberg_tables SET metadata_location = "
                "replace(metadata_location, ?, ?)", (old_text, new_text),
            )
            connection.commit()
        finally:
            connection.close()
        for metadata_file in (new_mirror / "warehouse").rglob("*.metadata.json"):
            metadata_file.write_text(metadata_file.read_text().replace(old_text, new_text))

        with pytest.raises(FileNotFoundError):
            _catalog_for(new_mirror).load_table("s.t").scan().to_arrow()


class TestWhatSurvivesInPlace:
    """What the lake DOES hold, checked where it was written.

    Separated from the portability question deliberately: these are
    true today and would remain true once paths are relative, so they
    are worth knowing independently of the defect above.
    """

    def test_the_data_is_there(self, lived_in_deployment):
        data_dir, mirror_dir = lived_in_deployment

        rows = _catalog_for(mirror_dir).load_table("s.t").scan().to_arrow().to_pydict()

        assert sorted(rows["id"]) == ["1", "2"]

    def test_the_raw_layer_is_there(self, lived_in_deployment):
        # Bronze is what makes a value explicable rather than merely
        # present.
        data_dir, mirror_dir = lived_in_deployment

        assert _catalog_for(mirror_dir).load_table(
            "bronze_s.t").scan().to_arrow().num_rows == 2

    def test_the_history_is_there(self, lived_in_deployment):
        """THE ONLY THING A RE-SYNC COULD NOT REBUILD.

        A source holds "now" and cannot say what a value used to be.
        Everything else in the lake is recoverable from the silos;
        this is not.
        """
        data_dir, mirror_dir = lived_in_deployment

        changelog = _catalog_for(mirror_dir).load_table(
            "changelog_s.t").scan().to_arrow().to_pydict()

        assert changelog["_change"] == ["UPDATE"]
        assert changelog["a"] == ["CHANGED"]

    def test_the_provenance_travels_with_the_table(self, lived_in_deployment):
        # Which silo and table each row came from, stamped on the table
        # rather than held in config -- so it survives whatever happens
        # to deployment/etc.
        data_dir, mirror_dir = lived_in_deployment

        properties = _catalog_for(mirror_dir).load_table("bronze_s.t").properties

        assert properties["elysium.source_silo"] == "s"
        assert properties["elysium.source_table"] == "t"


class TestWhatTheLakeCannotExplain:
    """Named rather than discovered, because a rebuild that silently
    loses the write log is worse than one that refuses to start.
    """

    def test_the_operational_state_does_not_survive(self, lived_in_deployment):
        data_dir, mirror_dir = lived_in_deployment
        preserved = _tear_down_keeping_the_lake(data_dir, mirror_dir)

        for name in ("write_log.db", "credentials.db", "config_history.db", "metrics.db"):
            assert not (preserved / name).exists()

    def test_nothing_says_what_the_data_MEANS(self, lived_in_deployment):
        """THE SECOND GAP, which would remain even if paths were
        relative.

        The lake holds tables, rows and provenance. It does not hold
        the ontology that says `t` is a Thing, the policy that says who
        may read it, or the silo definition that says where to re-sync
        from -- and by the control-plane standard all three belong in
        it.
        """
        data_dir, mirror_dir = lived_in_deployment

        properties = _catalog_for(mirror_dir).load_table("s.t").properties

        assert not any(key.startswith("elysium.ontology") for key in properties)
        assert not any(key.startswith("elysium.policy") for key in properties)


class TestObjectStorageMakesItPortable:
    """The fix, and it turns out to already exist.

    THE PROBLEM WAS NEVER "ICEBERG BAKES IN ABSOLUTE PATHS". It is that
    `file:///var/lib/mirror/...` is HOST-SPECIFIC while
    `s3://elysium/warehouse/...` is not. The same string resolves from
    any machine, any container, any mount -- so nothing needs
    rewriting when the lake moves, because as far as the lake is
    concerned it has not moved.

    That reframes the durable-storage phase. It was justified as "the
    mirror should survive the machine", which is true and incomplete:
    object storage is also what makes a preserved lake REBUILDABLE ON,
    and that is the requirement.

    THE CATALOG MUST STILL BE PRESERVED. It is a SQLite file listing
    where each table's metadata lives, and its CONTENTS are now
    portable -- but losing the file still leaves a bucket nobody can
    interpret, which is the mistake scripts/check_mirror warns about.
    """

    def test_a_lake_in_object_storage_survives_the_install_being_deleted(self, tmp_path):
        """THE REQUIREMENT, end to end.

        Sync into object storage, delete the entire installation,
        preserve only the catalog, read the data from somewhere else.
        """
        pytest.importorskip("moto.server")
        boto3 = pytest.importorskip("boto3")
        from moto.server import ThreadedMotoServer

        server = ThreadedMotoServer(port=0)
        server.start()
        try:
            host, port = server.get_host_and_port()
            endpoint = f"http://{host}:{port}"
            boto3.client(
                "s3", endpoint_url=endpoint, region_name="us-east-1",
                aws_access_key_id="testing", aws_secret_access_key="testing",
            ).create_bucket(Bucket="elysium")

            source = tmp_path / "source.db"
            connection = sqlite3.connect(source)
            connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
            connection.executemany(
                "INSERT INTO t VALUES (?, ?)", [("1", "x"), ("2", "y")])
            connection.commit()
            connection.close()

            storage = {
                "warehouse": "s3://elysium/warehouse",
                "s3.endpoint": endpoint,
                "s3.access-key-id": "testing",
                "s3.secret-access-key": "testing",
                "s3.region": "us-east-1",
            }
            install = tmp_path / "install"
            sync = IcebergMirrorSync(
                install, {"s": SQLiteReadAdapter({"path": source})}, storage=dict(storage),
            )
            sync.sync_table("s", "t", "id", COLUMNS, TYPES)

            # LOCATION-INDEPENDENT, which is the whole point.
            assert sync._catalog.load_table("s.t").metadata_location.startswith("s3://")

            # Preserve the catalog; destroy everything else.
            preserved = tmp_path / "preserved"
            preserved.mkdir()
            shutil.copy(install / "catalog.db", preserved / "catalog.db")
            shutil.rmtree(install)

            fresh = SqlCatalog(
                "elysium_mirror", uri=f"sqlite:///{preserved / 'catalog.db'}", **storage,
            )
            rows = fresh.load_table("s.t").scan().to_arrow().to_pydict()

            assert sorted(rows["id"]) == ["1", "2"]
        finally:
            server.stop()

    def test_a_local_lake_still_is_not(self, lived_in_deployment):
        # THE CONTROL, and the contrast that makes the point. The same
        # teardown against a file:// warehouse fails, which is why the
        # storage setting is the fix rather than a performance option.
        data_dir, mirror_dir = lived_in_deployment
        preserved = _tear_down_keeping_the_lake(data_dir, mirror_dir)

        with pytest.raises(FileNotFoundError):
            _catalog_for(preserved / "mirror").load_table("s.t").scan().to_arrow()
