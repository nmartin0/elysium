"""
A restore gives back the deployment AS IT WAS BACKED UP -- nothing more.

ROADMAP 1.3: "the script checks an inventory; only a real restore into
a stopped deployment proves one". The restore check had only ever
proved each database OPENS. This proves a restore over a deployment
that kept running after its backup returns the backup's state.

TWO DEFECTS IT FOUND, both of which let data from AFTER the backup
survive the restore:

  A. RESTORE ONLY ADDED. It copied the databases IN the backup and left
     the rest -- so a database absent at backup time and created since
     survived. A roles.db from after the backup meant a restore made to
     UNDO a bad role change left that change in force.

  B. LEFTOVER LOGS WERE REPLAYED. Every store runs in WAL mode. A
     deployment that crashed, or was not fully stopped, leaves x.db-wal
     beside x.db; restoring x.db alone let SQLite replay that stale log
     onto it, bringing post-backup rows back.

NOTHING IS DELETED. What a restore replaces is moved into a
`replaced-by-restore-<time>` folder, so a restore run by mistake can be
undone by hand.
"""

import sqlite3

import pytest

from core.notifications import NotificationStore
from core.role_store import RoleStore
from scripts.backup_deployment import backup
from scripts.restore_deployment import restore


def _summaries(path):
    connection = sqlite3.connect(path)
    try:
        return sorted(row[0] for row in connection.execute("SELECT summary FROM notifications"))
    finally:
        connection.close()


@pytest.fixture
def deployment(tmp_path):
    data, saved = tmp_path / "data", tmp_path / "backup"
    data.mkdir()
    NotificationStore(data / "notifications.db").notify("alice", "k", "BEFORE")
    backup(data, saved)
    return data, saved


class TestADatabaseAbsentFromTheBackup:
    def test_does_not_survive_the_restore(self, deployment):
        """DEFECT A. Roles edited after the backup must not outlive a
        restore made to go back to before them."""
        data, saved = deployment
        RoleStore(data / "roles.db").save({"late": {"allowed_actions": []}})

        restore(saved, data, force=True)

        assert RoleStore(data / "roles.db").load() is None


class TestALeftoverLog:
    def test_is_not_replayed_onto_the_restored_database(self, deployment):
        """DEFECT B. A connection still open -- a crash, or a deployment
        not fully stopped -- leaves the WAL beside the database."""
        data, saved = deployment
        live = sqlite3.connect(data / "notifications.db")
        live.execute("PRAGMA wal_autocheckpoint=0")
        live.execute(
            "INSERT INTO notifications (notification_id, user_id, created_at, "
            "kind, summary) VALUES ('late', 'alice', 't', 'k', 'AFTER')",
        )
        live.commit()
        wal = (data / "notifications.db-wal").read_bytes()
        live.close()
        (data / "notifications.db-wal").write_bytes(wal)

        restore(saved, data, force=True)

        assert _summaries(data / "notifications.db") == ["BEFORE"]


class TestNothingIsLost:
    def test_what_was_replaced_is_kept(self, deployment):
        """A RESTORE RUN BY MISTAKE can be undone by hand."""
        data, saved = deployment
        NotificationStore(data / "notifications.db").notify("alice", "k", "AFTER")

        restore(saved, data, force=True)

        (kept,) = [p for p in data.iterdir() if p.name.startswith("replaced-by-restore-")]
        assert _summaries(kept / "notifications.db") == ["AFTER", "BEFORE"]

    def test_what_is_not_elysiums_is_left_alone(self, deployment):
        """THE SILOS ARE CUSTOMER DATA. A restore replaces what Elysium
        owns and nothing else."""
        data, saved = deployment
        (data / "dev_fixtures").mkdir()
        (data / "dev_fixtures" / "mediator.db").write_text("customer data")

        restore(saved, data, force=True)

        assert (data / "dev_fixtures" / "mediator.db").read_text() == "customer data"


class TestTheBackupsStateIsExact:
    def test_the_restored_rows_are_the_backed_up_rows(self, deployment):
        data, saved = deployment
        NotificationStore(data / "notifications.db").notify("alice", "k", "AFTER")

        restore(saved, data, force=True)

        assert _summaries(data / "notifications.db") == ["BEFORE"]


class TestARestoredDeploymentWorks:
    """ROADMAP 1.3 ITSELF. A restore check that proves each database
    opens is an inventory; this restores a deployment that kept running
    after its backup, then BUILDS A GENERATION from what came back and
    uses it -- the account logs in, the roles are the backup's, and the
    mirror answers a search."""

    def test_end_to_end(self, tmp_path):
        import shutil

        from core.deployment_loader import build_generation, resolve_runtime_paths
        from core.intermediate_layer.auth import UserRecord
        from core.triggers import TriggerStore
        from core.user_directory import UserDirectory

        real = resolve_runtime_paths()
        data, saved = tmp_path / "data", tmp_path / "backup"
        shutil.copytree(real.data_dir, data)

        def generation():
            return build_generation(real.config_dir, data, real.log_dir)

        roles = generation().config.roles
        directory = UserDirectory(data / "credentials.db", roles)
        directory.create_user("restored", "a-long-password-1", "us-west", "debug")
        edited = {name: dict(role) for name, role in roles.items()}
        edited["auditor"] = {"allowed_actions": ["read:Customer"]}
        RoleStore(data / "roles.db").save(edited)
        TriggerStore(data / "triggers.db").create("restored", "Kept", "v1", above=1)
        NotificationStore(data / "notifications.db").notify("restored", "k", "BEFORE")

        backup(data, saved)

        # THE DEPLOYMENT KEEPS RUNNING after its backup.
        after = dict(edited)
        after["intruder"] = {"allowed_actions": ["read:Customer"]}
        RoleStore(data / "roles.db").save(after)
        TriggerStore(data / "triggers.db").create("restored", "Late", "v1", above=1)
        NotificationStore(data / "notifications.db").notify("restored", "k", "AFTER")

        restore(saved, data)

        restored = generation()
        assert "auditor" in restored.config.roles
        assert "intruder" not in restored.config.roles

        record = UserDirectory(data / "credentials.db", restored.config.roles) \
            .get_user_record("restored")
        assert record.role_name == "debug"

        names = [t.name for t in TriggerStore(data / "triggers.db").for_owner("restored")]
        assert names == ["Kept"]
        assert [n.summary for n in
                NotificationStore(data / "notifications.db").for_user("restored")] == ["BEFORE"]

        matched = restored.mediator.search_object(
            UserRecord("restored", "us-west", "debug"), "Transaction", [],
        )
        assert matched, "the restored mirror answered nothing"
