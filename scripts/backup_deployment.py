"""Capture a running deployment's own state, consistently.

    python -m scripts.backup_deployment /path/to/backup-dir
    python -m scripts.backup_deployment /path/to/backup-dir --check

WHY A SCRIPT RATHER THAN `cp`. Copying a live SQLite file tears across
a write: the copy can hold a half-applied transaction, and a torn
credentials database is one nobody can log into.
`sqlite3.Connection.backup()` takes a CONSISTENT snapshot of a
database being written to, which is the whole reason this exists.

WHAT IT CAPTURES: every database Elysium owns (OWNED_DATABASES), plus
the Iceberg warehouse.

WHAT IT DELIBERATELY DOES NOT: the data silos. `dev_fixtures/` stands
in for a CUSTOMER'S databases, and backing those up would be copying
data Elysium does not own into a directory the customer did not
choose. Their backup is their business, and ours quietly containing a
copy of it would be a surprise of the worst kind.

THE CHANGELOG IS THE ONE THING THAT CANNOT BE REBUILT. Bronze and
silver derive from the silos -- delete them and a sync restores them.
History does not: the record of what CHANGED between two syncs exists
only in the mirror, and nothing upstream remembers it.

RUN IT WHILE THE DEPLOYMENT IS RUNNING. That is the case this is for.
A stopped deployment can be copied with `cp -a`, and anyone who can
stop it does not need this.
"""

import argparse
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from core.deployment_loader import resolve_runtime_paths

# THE DATABASES ELYSIUM OWNS, relative to the data directory.
#
# THIS LIST HAS FALLEN BEHIND THE CODE TWICE, and the second time is
# why a test now compares it with what the code actually creates.
#
#   FIRST: "seven, not the five the roadmap listed" -- it missed the
#   mirror's catalog.db, and sync_attempts.db did not exist yet.
#
#   SECOND: pending_writes.db was added in the commit AFTER this
#   script, and saved_views, triggers and notifications arrived later.
#   None were listed. A restore would have dropped every waiting
#   approval, saved view, trigger and notification -- and the restore
#   check would have passed, because it checks against this same list.
#
# tests/unit/test_backup_inventory.py now finds every `<name>.db`
# opened under the data directory and fails if one is neither listed
# here nor excluded there with a reason.
#
# MISSING IS NOT AN ERROR. Several are created lazily on first use, so
# a young deployment genuinely has fewer and a backup should say so
# rather than fail.
OWNED_DATABASES = (
    "credentials.db",
    "write_log.db",
    "config_history.db",
    "metrics.db",
    "artifacts.db",
    "mirror/catalog.db",
    "mirror/sync_attempts.db",
    # The approvals queue -- database-authoritative since patch 276,
    # so there is no other copy of a waiting decision.
    "pending_writes.db",
    # THE JUDGEMENTS A PERSON MADE ABOUT WHO IS WHO (GOLD-6). Nothing
    # upstream remembers them: gold is rebuilt from silver on every
    # sync, and the merges it applies exist ONLY here. Losing this file
    # would silently un-merge every entity somebody had approved, and
    # the next sync would publish the un-merged version without
    # complaint. The backup guard caught it the moment the store
    # appeared, which is what that guard is for.
    "identity_decisions.db",
    "saved_views.db",
    "triggers.db",
    "notifications.db",
    # ONCE SOMEBODY EDITS A ROLE, THE ONLY COPY OF THE GRANTS. Losing it
    # on restore would silently fall back to policy.yaml -- restoring
    # every grant that had been deliberately withdrawn. The backup
    # guard caught this the moment the store was written.
    "roles.db",
)

# THE WAREHOUSE, copied as files rather than snapshotted.
#
# Iceberg metadata and Parquet are written once and never modified, so
# a file copy cannot tear one. What it CAN do is catch a table
# mid-commit -- some files written, the catalog not yet pointing at
# them -- and that is harmless in this direction: the extra files are
# ignored by a catalog that does not name them.
WAREHOUSE = "mirror/warehouse"


def _snapshot_database(source: Path, destination: Path) -> None:
    """A consistent copy of a database that may be being written to."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as live, sqlite3.connect(destination) as copy:
        live.backup(copy)


def backup(data_dir: Path, into: Path) -> dict:
    """Captures what Elysium owns. Returns what it captured."""
    into.mkdir(parents=True, exist_ok=True)
    captured, absent = [], []

    for name in OWNED_DATABASES:
        source = data_dir / name
        if not source.exists():
            absent.append(name)
            continue
        _snapshot_database(source, into / name)
        captured.append(name)

    warehouse = data_dir / WAREHOUSE
    warehouse_files = 0
    if warehouse.is_dir():
        shutil.copytree(warehouse, into / WAREHOUSE, dirs_exist_ok=True)
        warehouse_files = sum(1 for p in (into / WAREHOUSE).rglob("*") if p.is_file())

    (into / "BACKUP_TAKEN_AT").write_text(
        f"{datetime.now(UTC).isoformat()}\n"
        f"from: {data_dir.resolve()}\n"
        f"databases: {len(captured)}\n"
        f"warehouse files: {warehouse_files}\n"
        # SAYING WHAT IS ABSENT MATTERS AS MUCH AS WHAT IS PRESENT. A
        # restore that quietly lacks credentials.db is one nobody can
        # log into, and the moment to notice is now.
        f"absent: {', '.join(absent) if absent else 'none'}\n"
        # THE SILOS ARE NOT HERE, stated in the backup itself so that
        # whoever restores from it is not surprised.
        f"\nNOT INCLUDED: the data silos. Elysium does not own them.\n",
    )
    return {"captured": captured, "absent": absent, "warehouse_files": warehouse_files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path,
                        help="directory to write the backup into")
    parser.add_argument("--check", action="store_true",
                        help="report what WOULD be captured, and write nothing")
    args = parser.parse_args()

    data_dir = Path(resolve_runtime_paths().data_dir)

    if args.check:
        for name in OWNED_DATABASES:
            source = data_dir / name
            state = "present" if source.exists() else "ABSENT"
            print(f"  {state:8} {name}")
        warehouse = data_dir / WAREHOUSE
        files = sum(1 for p in warehouse.rglob("*") if p.is_file()) if warehouse.is_dir() else 0
        print(f"  warehouse: {files} file(s)")
        print("\nNOT INCLUDED: the data silos. Elysium does not own them.")
        return 0

    result = backup(data_dir, args.destination)
    print(f"captured {len(result['captured'])} database(s) and "
          f"{result['warehouse_files']} warehouse file(s) into {args.destination}")
    if result["absent"]:
        # NOT A FAILURE, and not silent either. A young deployment
        # genuinely lacks the lazily-created ones.
        print(f"absent (not yet created): {', '.join(result['absent'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
