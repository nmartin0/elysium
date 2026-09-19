"""
A backup is checked before it is trusted.

WHY A SCRIPT WHEN `cp -a` WOULD COPY IT. The copying is the easy half
and was never the problem. What `cp -a` cannot do is tell you the
backup is WORTH restoring -- that every database opens, that nothing
essential is missing, and that the thing you are about to depend on is
complete.

THE MOMENT TO FIND OUT IS BEFORE THE RESTORE, NOT AFTER. A backup
missing credentials.db restores silently and then nobody can log in,
which looks like a different failure entirely.
"""

import sqlite3

import pytest

from scripts.backup_deployment import OWNED_DATABASES, WAREHOUSE, backup
from scripts.restore_deployment import UnusableBackup, inspect_backup, restore


@pytest.fixture
def data_dir(tmp_path):
    source = tmp_path / "live"
    for name in ("credentials.db", "write_log.db", "mirror/catalog.db"):
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE t (a TEXT)")
        conn.execute("INSERT INTO t VALUES ('kept')")
        conn.commit()
        conn.close()
    warehouse = source / WAREHOUSE / "ns" / "table" / "metadata"
    warehouse.mkdir(parents=True)
    (warehouse / "00000.metadata.json").write_text("{}")
    return source


@pytest.fixture
def backup_dir(data_dir, tmp_path):
    destination = tmp_path / "backup"
    backup(data_dir, destination)
    return destination


class TestAGoodBackupPasses:
    def test_it_reports_no_problems(self, backup_dir):
        assert inspect_backup(backup_dir)["problems"] == []

    def test_it_lists_what_is_present(self, backup_dir):
        present = " ".join(inspect_backup(backup_dir)["present"])

        assert "credentials.db" in present

    def test_it_lists_what_is_absent_without_complaining(self, backup_dir):
        """LAZILY-CREATED DATABASES ARE LEGITIMATELY MISSING from a
        young deployment. Absent is reported; only credentials.db is a
        problem."""
        report = inspect_backup(backup_dir)

        assert "artifacts.db" in report["absent"]
        assert report["problems"] == []


class TestABrokenBackupIsCaught:
    def test_missing_credentials_is_a_problem(self, backup_dir):
        (backup_dir / "credentials.db").unlink()

        problems = " ".join(inspect_backup(backup_dir)["problems"])

        assert "nobody can log into" in problems

    def test_a_missing_manifest_is_a_problem(self, backup_dir):
        """THE MANIFEST IS HOW A BACKUP IDENTIFIES ITSELF. Without it
        this may be any directory at all, and restoring an arbitrary
        directory over a deployment is worse than refusing."""
        (backup_dir / "BACKUP_TAKEN_AT").unlink()

        problems = " ".join(inspect_backup(backup_dir)["problems"])

        assert "may not be a backup directory" in problems

    def test_a_file_that_is_not_a_database_is_caught(self, backup_dir):
        """OPENING IS NOT ENOUGH. sqlite3.connect() succeeds on a file
        that is not a database at all -- it only fails when something
        reads, so the check reads the schema."""
        (backup_dir / "write_log.db").write_text("not a database")

        problems = " ".join(inspect_backup(backup_dir)["problems"])

        assert "does not open as a database" in problems

    def test_a_directory_that_is_not_a_backup_is_refused(self, tmp_path):
        with pytest.raises(UnusableBackup):
            inspect_backup(tmp_path / "never-existed")

    def test_every_problem_is_reported_not_just_the_first(self, backup_dir):
        """SOMEBODY FIXING A BACKUP ONE ERROR AT A TIME, with a restore
        between each, is somebody who will give up before the
        third."""
        (backup_dir / "credentials.db").unlink()
        (backup_dir / "BACKUP_TAKEN_AT").unlink()

        assert len(inspect_backup(backup_dir)["problems"]) == 2


class TestRestoring:
    def test_it_puts_the_databases_back(self, backup_dir, tmp_path):
        target = tmp_path / "restored"

        restore(backup_dir, target)

        conn = sqlite3.connect(target / "credentials.db")
        assert conn.execute("SELECT a FROM t").fetchone()[0] == "kept"

    def test_it_puts_the_warehouse_back(self, backup_dir, tmp_path):
        target = tmp_path / "restored"

        restore(backup_dir, target)

        assert (target / WAREHOUSE).is_dir()

    def test_it_refuses_a_backup_with_problems(self, backup_dir, tmp_path):
        (backup_dir / "credentials.db").unlink()

        with pytest.raises(UnusableBackup, match="not restored"):
            restore(backup_dir, tmp_path / "restored")

    def test_force_overrides_the_refusal(self, backup_dir, tmp_path):
        """AN OPERATOR WITH A DAMAGED BACKUP AND NO OTHER may still
        want what is in it. Refusing absolutely would make this script
        something people work around with cp."""
        (backup_dir / "credentials.db").unlink()

        restore(backup_dir, tmp_path / "restored", force=True)

        assert (tmp_path / "restored" / "write_log.db").exists()


def test_the_inventory_is_shared_with_the_backup():
    """ONE LIST, NOT TWO. A database added to the backup and not the
    restore is a database silently dropped on the way back."""
    import scripts.restore_deployment as module

    assert module.OWNED_DATABASES is OWNED_DATABASES
