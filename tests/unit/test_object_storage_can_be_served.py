"""
Every reader opens the lake the way the writer wrote it (PA001-F5).

THE FAILURE. A deployment configured for S3 or MinIO syncs perfectly
and writes `s3://lake/w/...`. Then the server cannot build a
generation: the catalog stores ABSOLUTE metadata locations, and loading
a table without the endpoint and credentials raises OSError, which
escapes build_generation(). The deployment works until its first sync
and then cannot start, restart or reload.

WHY NOBODY SAW IT. The same four lines were written out at SIX call
sites -- the sync, two in deployment_loader (serving, and the gold
binding), two in api/routes.py, and scripts/check_mirror.py. FIVE
hard-coded a local `file://` warehouse. Only the sync, the WRITER,
passed the deployment's storage options.

And the one existing S3 test reads back through the SYNC's own
catalog, which has the credentials -- so it passed while the server
could not have read a byte.

THE RULE NOW: nothing constructs SqlCatalog directly; there is one
factory. A reader that cannot read what the writer wrote is not a
reader, and five copies of a decision is five chances to make it
differently.
"""

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from adapters.sqlite_adapter import SQLiteReadAdapter
from core.deployment_loader import _build_read_adapters
from core.mirror.catalog import open_mirror_catalog
from core.mirror.iceberg_sync import IcebergMirrorSync

TYPE_CONFIG = {"storage": {"table": "customers", "id_column": "customer_id"}}
SCHEMA = {"C": {"storage": {"silo": "p", "table": "customers",
                             "id_column": "customer_id"}, "fields": {"name": {}}}}


def _source(tmp_path, name):
    path = tmp_path / f"{name}.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE customers (customer_id TEXT, name TEXT)")
    conn.execute("INSERT INTO customers VALUES ('c1','Ada')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def s3(monkeypatch):
    """A real S3 protocol, locally: moto serves it, pyiceberg's S3
    client talks to it, and nothing about the code under test knows
    the difference."""
    pytest.importorskip("moto")
    import boto3
    from moto.server import ThreadedMotoServer

    for key in [k for k in os.environ if k.startswith("AWS_")]:
        monkeypatch.delenv(key)
    server = ThreadedMotoServer(port=0)
    server.start()
    try:
        host, port = server.get_host_and_port()
        endpoint = f"http://{host}:{port}"
        boto3.client("s3", endpoint_url=endpoint, region_name="us-east-1",
                     aws_access_key_id="t", aws_secret_access_key="t").create_bucket(
            Bucket="lake")
        yield {"warehouse": "s3://lake/w", "s3.endpoint": endpoint,
               "s3.access-key-id": "t", "s3.secret-access-key": "t",
               "s3.region": "us-east-1"}
    finally:
        server.stop()


class TestTheServingPath:
    def test_an_object_store_mirror_can_be_read_by_the_server(self, tmp_path, s3):
        """THE REGRESSION TEST: this is exactly what build_generation
        does, and it used to raise OSError."""
        source = _source(tmp_path, "s")
        sync = IcebergMirrorSync(tmp_path / "mirror",
                                  {"p": SQLiteReadAdapter({"path": source})}, storage=s3)
        sync.sync_table("p", "customers", "customer_id", ["customer_id", "name"], {})

        config = SimpleNamespace(read_from_mirror=True, schema=SCHEMA, mirror_storage=s3)
        adapters = _build_read_adapters(config, {"p": {}}, tmp_path)

        assert adapters["p"].get_raw_field("C", "c1", "name", TYPE_CONFIG) == "Ada"

    def test_the_sync_really_wrote_to_object_storage(self, tmp_path, s3):
        """Otherwise the test above could pass against a local
        warehouse and prove nothing."""
        source = _source(tmp_path, "s")
        sync = IcebergMirrorSync(tmp_path / "mirror",
                                  {"p": SQLiteReadAdapter({"path": source})}, storage=s3)
        sync.sync_table("p", "customers", "customer_id", ["customer_id", "name"], {})

        location = sync.catalog.load_table("p.customers").metadata_location
        assert location.startswith("s3://lake/w/")


class TestTheLocalPathIsUnchanged:
    def test_a_deployment_with_no_storage_options_still_works(self, tmp_path):
        """The overwhelmingly common case, and the one a factory could
        most easily have broken."""
        source = _source(tmp_path, "local")
        sync = IcebergMirrorSync(tmp_path / "mirror",
                                  {"p": SQLiteReadAdapter({"path": source})})
        sync.sync_table("p", "customers", "customer_id", ["customer_id", "name"], {})

        config = SimpleNamespace(read_from_mirror=True, schema=SCHEMA, mirror_storage={})
        adapters = _build_read_adapters(config, {"p": {}}, tmp_path)

        assert adapters["p"].get_raw_field("C", "c1", "name", TYPE_CONFIG) == "Ada"

    def test_the_default_warehouse_is_the_mirror_directory(self, tmp_path):
        catalog = open_mirror_catalog(tmp_path / "mirror")

        assert catalog.properties["warehouse"] == (tmp_path / "mirror" / "warehouse").as_uri()

    def test_a_declared_warehouse_wins(self, tmp_path):
        catalog = open_mirror_catalog(tmp_path / "mirror", {"warehouse": "s3://x/y"})

        assert catalog.properties["warehouse"] == "s3://x/y"

    def test_other_options_are_passed_through_untouched(self, tmp_path):
        """pyiceberg owns that vocabulary. Enumerating it here would
        mean revisiting this function every time it gains a key."""
        catalog = open_mirror_catalog(tmp_path / "mirror",
                                       {"s3.region": "eu-west-2", "s3.endpoint": "http://x"})

        assert catalog.properties["s3.region"] == "eu-west-2"
        assert catalog.properties["s3.endpoint"] == "http://x"


class TestNobodyOpensTheCatalogTheirOwnWay:
    """A tripwire, in the spirit of the ones already in tests/unit. The
    defect was not one bad line: it was the SAME line copied five
    times, so five readers could disagree with the writer. Copying it
    again must fail here rather than in production, months later, on
    somebody's S3 deployment."""

    def test_only_the_factory_constructs_a_catalog(self):
        root = Path(__file__).resolve().parent.parent.parent
        offenders = []
        for directory in ("core", "api", "adapters", "scripts"):
            for path in (root / directory).rglob("*.py"):
                if path.name == "catalog.py" and path.parent.name == "mirror":
                    continue
                if "SqlCatalog(" in path.read_text():
                    offenders.append(str(path.relative_to(root)))

        assert not offenders, (
            f"{offenders} construct SqlCatalog directly. Use "
            f"core.mirror.catalog.open_mirror_catalog, or an S3 deployment will "
            f"sync and then be unreadable (PA001-F5).")
