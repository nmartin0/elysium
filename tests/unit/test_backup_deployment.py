"""
A running deployment can be captured consistently.

WHY A SCRIPT RATHER THAN `cp`. Copying a live SQLite file tears across
a write: the copy can hold a half-applied transaction, and a torn
credentials database is one nobody can log into.
`sqlite3.Connection.backup()` takes a consistent snapshot of a
database being written to, which is the whole reason this exists.

THE INVENTORY WAS WRONG IN THE ROADMAP. It named five databases --
credentials, write_log, config_history, metrics, artifacts -- and
missed the mirror's own catalog.db. sync_attempts.db did not exist
when it was written. Seven, verified against the live deployment.

THE SILOS ARE DELIBERATELY EXCLUDED. `dev_fixtures/` stands in for a
CUSTOMER'S databases, and backing those up would copy data Elysium
does not own into a directory the customer did not choose.
"""

import sqlite3

import pytest

from scripts.backup_deployment import OWNED_DATABASES, WAREHOUSE, backup


@pytest.fixture
def data_dir(tmp_path):
    """A deployment-shaped directory, including a silo that must NOT
    be captured."""
    for name in ("credentials.db", "write_log.db", "mirror/catalog.db"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t (a TEXT)")
        conn.execute("INSERT INTO t VALUES ('kept')")
        conn.commit()
        conn.close()

    warehouse = tmp_path / WAREHOUSE / "ns" / "table" / "metadata"
    warehouse.mkdir(parents=True)
    (warehouse / "00000.metadata.json").write_text("{}")

    silo = tmp_path / "dev_fixtures"
    silo.mkdir()
    conn = sqlite3.connect(silo / "customer.db")
    conn.execute("CREATE TABLE secret (a TEXT)")
    conn.commit()
    conn.close()

    return tmp_path


class TestWhatItCaptures:
    def test_it_captures_the_databases_that_exist(self, data_dir, tmp_path):
        result = backup(data_dir, tmp_path / "out")

        assert "credentials.db" in result["captured"]
        assert "mirror/catalog.db" in result["captured"]

    def test_a_captured_database_opens_and_holds_its_rows(self, data_dir, tmp_path):
        """THE POINT OF backup() OVER cp: the copy must be a usable
        database, not a file that happens to be the right size."""
        backup(data_dir, tmp_path / "out")

        conn = sqlite3.connect(tmp_path / "out" / "credentials.db")
        assert conn.execute("SELECT a FROM t").fetchone()[0] == "kept"

    def test_it_captures_the_warehouse(self, data_dir, tmp_path):
        result = backup(data_dir, tmp_path / "out")

        assert result["warehouse_files"] == 1

    def test_absent_databases_are_reported_not_fatal(self, data_dir, tmp_path):
        """artifacts.db AND sync_attempts.db ARE CREATED LAZILY, so a
        young deployment genuinely has fewer than seven. Failing would
        make a backup impossible until every feature had been used
        once."""
        result = backup(data_dir, tmp_path / "out")

        assert "artifacts.db" in result["absent"]


class TestWhatItRefusesToCapture:
    def test_the_silos_are_not_copied(self, data_dir, tmp_path):
        """A CUSTOMER'S DATABASE IS NOT OURS TO BACK UP. A backup
        directory quietly containing a copy of their data would be a
        surprise of the worst kind."""
        backup(data_dir, tmp_path / "out")

        assert not (tmp_path / "out" / "dev_fixtures").exists()

    def test_and_the_manifest_says_so(self, data_dir, tmp_path):
        # Stated in the backup itself, so whoever restores from it is
        # not left to discover the absence.
        backup(data_dir, tmp_path / "out")

        manifest = (tmp_path / "out" / "BACKUP_TAKEN_AT").read_text()
        assert "NOT INCLUDED: the data silos" in manifest


class TestTheManifest:
    def test_it_records_what_was_absent(self, data_dir, tmp_path):
        """A RESTORE THAT QUIETLY LACKS credentials.db is one nobody
        can log into, and the moment to notice is when the backup is
        taken."""
        backup(data_dir, tmp_path / "out")

        assert "artifacts.db" in (tmp_path / "out" / "BACKUP_TAKEN_AT").read_text()

    def test_it_records_where_the_backup_came_from(self, data_dir, tmp_path):
        backup(data_dir, tmp_path / "out")

        manifest = (tmp_path / "out" / "BACKUP_TAKEN_AT").read_text()
        assert str(data_dir.resolve()) in manifest


def test_it_snapshots_rather_than_copying():
    """A SOURCE-LEVEL TRIPWIRE, because the difference only shows
    under a concurrent write.

    `shutil.copy2` of an IDLE database produces a perfectly working
    copy, so a control swapping backup() for copy2 passes every
    behavioural test here. Demonstrating the difference needs a write
    in flight during the copy -- and an attempt to stage one found
    that backup() BLOCKS while an uncommitted transaction is open on
    the same connection, which is correct behaviour and not a usable
    test.

    So the mechanism is pinned directly, the way this project already
    guards the sync's adapters and the metadata row counts.
    """
    import inspect

    import scripts.backup_deployment as module

    source = inspect.getsource(module._snapshot_database)

    assert ".backup(" in source
    assert "copy2" not in source


def test_the_inventory_matches_what_a_deployment_has():
    """THE ROADMAP SAID FIVE AND MISSED TWO. Pinned so the list cannot
    quietly fall behind: a database added without being backed up is a
    database lost on the first restore."""
    assert "mirror/catalog.db" in OWNED_DATABASES
    assert "mirror/sync_attempts.db" in OWNED_DATABASES
    assert len(OWNED_DATABASES) == 7
