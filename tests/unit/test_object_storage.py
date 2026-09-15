"""
The mirror can live in object storage, not only on one machine's disk.

WHY THIS LANDS BEFORE THE CHANGELOG rather than after. Everything in
the mirror today is DERIVABLE from the silos: lose the machine,
reinstall, re-sync, and nothing is gone that the organisation's own
databases do not still hold. Object storage would make that faster, not
safer.

That stops being true the moment a changelog exists. A source database
holds "now" -- it has no record of what a value used to be -- so once
we append history, losing it loses everything the sources have since
overwritten, and no re-sync recovers it. At that point the mirror
becomes a SYSTEM OF RECORD, and a system of record on one machine's
disk is one power supply away from gone.

Shipping the changelog first would leave a window in which an
organisation accumulates history it believes is safe.

LOCAL REMAINS THE DEFAULT, because that is correct for one host and
every deployment today is one host.

THE CATALOG IS A SEPARATE AXIS. pyiceberg's CatalogType is REST, HIVE,
GLUE, DYNAMODB, SQL, IN_MEMORY, BIGQUERY; storage is chosen
independently through FileIO. Moving the warehouse does not require
moving the catalog, and an earlier draft of the roadmap wrongly coupled
them.
"""

import pathlib
import sqlite3

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.mirror.iceberg_sync import IcebergMirrorSync

COLUMNS = ["id", "a"]
TYPES = {"id": "string", "a": "string"}

pytest.importorskip("moto.server", reason="needs moto to simulate S3")
boto3 = pytest.importorskip("boto3", reason="needs boto3 to simulate S3")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id TEXT PRIMARY KEY, a TEXT)")
    connection.executemany("INSERT INTO t VALUES (?, ?)", [("1", "x"), ("2", "y")])
    connection.commit()
    connection.close()
    return path


def test_local_storage_is_the_default(tmp_path, source):
    # THE CONTROL, and the case every deployment is in today. A change
    # that required configuration would break all of them.
    sync = IcebergMirrorSync(tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})})
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    table = sync._catalog.load_table("s.t")
    assert table.metadata_location.startswith("file://")
    assert (tmp_path / "mirror" / "warehouse").is_dir()


def test_a_configured_warehouse_is_used_instead(tmp_path, source):
    # The warehouse moves without the catalog moving -- separate axes,
    # and the catalog stays SQL-over-SQLite here.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    sync = IcebergMirrorSync(
        tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})},
        storage={"warehouse": f"file://{elsewhere}"},
    )
    sync.sync_table("s", "t", "id", COLUMNS, TYPES)

    table = sync._catalog.load_table("s.t")
    assert str(elsewhere) in table.metadata_location
    assert not (tmp_path / "mirror" / "warehouse").exists()


def test_storage_options_reach_the_catalog(tmp_path, source):
    """The S3 credentials and endpoint a deployment configures.

    Passed through rather than interpreted: pyiceberg names them
    (s3.endpoint, s3.access-key-id and so on), and this layer should
    not invent its own vocabulary for someone else's options.
    """
    sync = IcebergMirrorSync(
        tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})},
        storage={"warehouse": f"file://{tmp_path / 'w'}", "s3.region": "eu-west-2"},
    )

    assert sync._catalog.properties["s3.region"] == "eu-west-2"


def test_the_mirror_really_works_over_s3(tmp_path, source):
    """END TO END, against a real S3 endpoint rather than a mock.

    moto's decorator patches boto3, which pyiceberg does NOT use -- it
    goes through PyArrow's own S3 client and tries a real connection.
    Found by trying it: the decorator version failed with a curl
    connection error. A standalone server on a port is what actually
    exercises the path.
    """
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

        sync = IcebergMirrorSync(
            tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})},
            storage={
                "warehouse": "s3://elysium/warehouse",
                "s3.endpoint": endpoint,
                "s3.access-key-id": "testing",
                "s3.secret-access-key": "testing",
                "s3.region": "us-east-1",
            },
        )
        sync.sync_table("s", "t", "id", COLUMNS, TYPES)

        table = sync._catalog.load_table("s.t")
        assert table.metadata_location.startswith("s3://")
        assert table.scan().to_arrow().num_rows == 2
    finally:
        server.stop()


def test_bronze_goes_to_object_storage_too(tmp_path, source):
    # Bronze is the layer that will hold history, so it is the one that
    # most needs to survive the machine. A warehouse setting that moved
    # silver and left bronze behind would be worse than none.
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

        sync = IcebergMirrorSync(
            tmp_path / "mirror", {"s": SQLiteReadAdapter({"path": source})},
            storage={
                "warehouse": "s3://elysium/warehouse",
                "s3.endpoint": endpoint,
                "s3.access-key-id": "testing",
                "s3.secret-access-key": "testing",
                "s3.region": "us-east-1",
            },
        )
        sync.sync_table("s", "t", "id", COLUMNS, TYPES)

        bronze = sync._catalog.load_table("bronze_s.t")
        assert bronze.metadata_location.startswith("s3://")
    finally:
        server.stop()


class TestReachableFromConfig:
    """A deployment can actually set this, not just the class.

    THE GAP THIS CLOSES. The storage parameter was built and verified
    end to end against a real S3 endpoint -- and nothing passed it.
    run_sync.py and deployment_loader.py both constructed the sync
    without it, so a deployment wanting its mirror in object storage
    had no way to say so.

    The same shape as the `readable` flag FastAPI silently stripped:
    built correctly, never wired. And the same lesson as the rule in
    AGENTS.md about mocked callbacks -- I tested the constructor, not
    the path a deployment takes to reach it.

    THROUGH load_deployment() AND REAL FILES, not a helper. The whole
    failure was a gap between a class and the path to it, so a test
    that skipped the path would repeat the mistake.
    """

    @staticmethod
    def _deployment(tmp_path, mirror_section):
        """A copy of the shipped deployment with config.yaml edited."""
        import shutil

        source = pathlib.Path(__file__).resolve().parents[2] / "deployment" / "etc"
        target = tmp_path / "etc"
        shutil.copytree(source, target)

        config = (target / "config.yaml").read_text()
        config = config[:config.index("\nmirror:")] + "\n" + mirror_section
        (target / "config.yaml").write_text(config)
        return target

    def test_no_mirror_section_means_local(self, tmp_path):
        from core.deployment_loader import load_deployment

        config = load_deployment(self._deployment(tmp_path, ""))

        assert config.mirror_storage == {}

    def test_an_all_comment_mirror_section_is_not_a_crash(self, tmp_path):
        """YAML parses a section whose every line is a comment as None.

        Not hypothetical: a commented-out example is exactly what the
        shipped config.yaml contains, and `config.get("mirror", {})`
        returns None there rather than {}. Found by the deployment
        linter the moment the example was written, which is what it is
        for.
        """
        from core.deployment_loader import load_deployment

        config = load_deployment(self._deployment(tmp_path, "mirror:\n  # nothing but comments\n"))

        assert config.mirror_storage == {}
        assert config.read_from_mirror is False

    def test_storage_settings_reach_the_config(self, tmp_path):
        from core.deployment_loader import load_deployment

        section = (
            "mirror:\n"
            "  storage:\n"
            '    warehouse: "s3://bucket/w"\n'
            '    s3.region: "eu-west-2"\n'
        )
        config = load_deployment(self._deployment(tmp_path, section))

        assert config.mirror_storage["warehouse"] == "s3://bucket/w"
        assert config.mirror_storage["s3.region"] == "eu-west-2"


def test_run_sync_passes_the_storage_setting_to_the_mirror(tmp_path, monkeypatch):
    """THE LAST LINK, and a control caught it missing.

    The config now carries the setting and the class now accepts it --
    and for one commit nothing connected them. A control removing the
    argument from run_sync.py failed NOTHING, because every test either
    built the config or built the sync, and none followed the path
    between.

    That is the third instance of this shape recorded in AGENTS.md, and
    the second time I have introduced it while fixing an earlier one.
    """
    import scripts.run_sync as run_sync

    seen = {}

    class Recording:
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)

        def sync_table(self, *args, **kwargs):
            raise AssertionError("not reached: the constructor is what is under test")

    monkeypatch.setattr(run_sync, "IcebergMirrorSync", Recording)
    monkeypatch.setattr(run_sync, "resolve_sync_targets", lambda schema: [])

    run_sync.run_sync()

    assert "storage" in seen, "run_sync must pass the deployment's storage setting"
