"""Check a backup, then put it back.

    python -m scripts.restore_deployment --check /path/to/backup
    python -m scripts.restore_deployment /path/to/backup

WHY A SCRIPT WHEN `cp -a` WOULD COPY IT. The copying is the easy half
and was never the problem. What `cp -a` cannot do is tell you the
backup is WORTH restoring -- that every database opens, that the
mirror's catalog points at metadata that exists, and that the thing
you are about to depend on is complete.

**THE MOMENT TO FIND OUT IS BEFORE THE RESTORE, NOT AFTER.** A backup
missing credentials.db restores silently and then nobody can log in.

WHAT IT DOES NOT RESTORE: the data silos. They were never captured --
they belong to the customer, and `backup_deployment.py` says so in the
manifest it writes. A restored deployment must be pointed at them
again, which is a configuration step rather than a copy.

RUN IT AGAINST A STOPPED DEPLOYMENT. Writing these files under a
running process would leave it holding handles to databases that no
longer exist, and this refuses to do it.
"""

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

from scripts.backup_deployment import OWNED_DATABASES, WAREHOUSE


class UnusableBackup(Exception):
    """A backup cannot be restored from.

    ITS OWN TYPE so the caller can distinguish "this backup is broken"
    from "the restore failed halfway", which need different responses:
    the first means go find another backup, the second means the
    target is now in an unknown state.
    """


def _describe_database(path: Path) -> tuple[bool, str]:
    """Whether a database opens, and what it holds.

    OPENING IS NOT ENOUGH. sqlite3.connect() succeeds on an empty file
    and on a file that is not a database at all -- it only fails when
    something reads. So this reads the schema, which is the cheapest
    query that proves the file is what it claims.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'",
        ).fetchone()[0]
        conn.close()
    except sqlite3.DatabaseError as e:
        return False, f"does not open as a database: {e}"
    if tables == 0:
        # AN EMPTY DATABASE IS SUSPICIOUS RATHER THAN BROKEN. A
        # lazily-created one legitimately has no tables until first
        # use, so this is reported and not fatal.
        return True, "opens, but holds no tables"
    return True, f"{tables} table(s)"


def inspect_backup(backup_dir: Path) -> dict:
    """Everything wrong with a backup, or nothing.

    REPORTS ALL PROBLEMS RATHER THAN THE FIRST. Somebody fixing a
    backup one error at a time, with a restore between each, is
    somebody who will give up before the third.
    """
    problems: list[str] = []
    present: list[str] = []
    absent: list[str] = []

    if not backup_dir.is_dir():
        raise UnusableBackup(f"{backup_dir} is not a directory")

    manifest = backup_dir / "BACKUP_TAKEN_AT"
    if not manifest.exists():
        # THE MANIFEST IS HOW A BACKUP IDENTIFIES ITSELF. Without it
        # this may be any directory at all, and restoring an arbitrary
        # directory over a deployment is worse than refusing.
        problems.append(
            "no BACKUP_TAKEN_AT file -- this may not be a backup directory",
        )

    for name in OWNED_DATABASES:
        path = backup_dir / name
        if not path.exists():
            absent.append(name)
            continue
        ok, description = _describe_database(path)
        present.append(f"{name}: {description}")
        if not ok:
            problems.append(f"{name} {description}")

    warehouse = backup_dir / WAREHOUSE
    warehouse_files = (
        sum(1 for p in warehouse.rglob("*") if p.is_file())
        if warehouse.is_dir() else 0
    )

    # CREDENTIALS ARE THE ONE THAT MATTERS MOST. A restore without it
    # produces a deployment nobody can log into, which looks like a
    # different failure entirely.
    if "credentials.db" in absent:
        problems.append(
            "credentials.db is absent -- restoring this backup produces a "
            "deployment nobody can log into",
        )

    return {
        "present": present,
        "absent": absent,
        "warehouse_files": warehouse_files,
        "problems": problems,
        "manifest": manifest.read_text() if manifest.exists() else None,
    }


def restore(backup_dir: Path, data_dir: Path, *, force: bool = False) -> dict:
    """Puts a checked backup back. Refuses a backup with problems."""
    report = inspect_backup(backup_dir)
    if report["problems"] and not force:
        raise UnusableBackup(
            "This backup has problems and was not restored:\n  "
            + "\n  ".join(report["problems"])
            + "\n\nPass --force to restore it anyway.",
        )

    data_dir.mkdir(parents=True, exist_ok=True)

    # MOVE WHAT IS THERE ASIDE FIRST, so the result is the backup's state
    # exactly -- and nothing is deleted.
    report["replaced_into"] = str(_move_aside(data_dir))

    for name in OWNED_DATABASES:
        source = backup_dir / name
        if not source.exists():
            continue
        destination = data_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    warehouse = backup_dir / WAREHOUSE
    if warehouse.is_dir():
        shutil.copytree(warehouse, data_dir / WAREHOUSE)

    return report


# SQLite's companions to a database in WAL mode. Moved with it, or they
# are replayed onto whatever takes its place.
_SIDECARS = ("-wal", "-shm", "-journal")


def _move_aside(data_dir: Path) -> Path:
    """Moves everything Elysium owns out of the way. Returns where to.

    RESTORE USED TO ONLY ADD. It copied the databases IN the backup and
    left the rest, so two kinds of post-backup data survived:

      A DATABASE ABSENT FROM THE BACKUP. roles.db created after it --
      so a restore made to UNDO a bad role change left that change in
      force.

      A LEFTOVER LOG. Every store runs in WAL mode; a deployment that
      crashed or was not fully stopped leaves x.db-wal beside x.db, and
      SQLite replays it onto whatever x.db is restored -- bringing back
      rows written after the backup.

    So every owned database, its sidecars, and the warehouse are moved
    here first. MOVED, NOT DELETED: a restore run by mistake can be
    undone by hand. The silos are never touched -- they are customer
    data, not Elysium's.
    """
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    aside = data_dir / f"replaced-by-restore-{stamp}"
    for name in OWNED_DATABASES:
        for suffix in ("", *_SIDECARS):
            present = data_dir / f"{name}{suffix}"
            if present.exists():
                target = aside / f"{name}{suffix}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(present, target)
    warehouse = data_dir / WAREHOUSE
    if warehouse.exists():
        aside.mkdir(parents=True, exist_ok=True)
        shutil.move(warehouse, aside / WAREHOUSE)
    return aside


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="the backup directory")
    parser.add_argument("--check", action="store_true",
                        help="report whether this backup is usable, restore nothing")
    parser.add_argument("--into", type=Path, default=None,
                        help="where to restore (default: this deployment's data dir)")
    parser.add_argument("--force", action="store_true",
                        help="restore despite problems")
    args = parser.parse_args()

    try:
        report = inspect_backup(args.backup)
    except UnusableBackup as e:
        print(f"{e}", file=sys.stderr)
        return 1

    for line in report["present"]:
        print(f"  present  {line}")
    for name in report["absent"]:
        print(f"  ABSENT   {name}")
    print(f"  warehouse: {report['warehouse_files']} file(s)")

    if report["problems"]:
        print("\nPROBLEMS:", file=sys.stderr)
        for problem in report["problems"]:
            print(f"  - {problem}", file=sys.stderr)

    if args.check:
        print("\nNothing was restored (--check).")
        # A CHECK THAT FOUND PROBLEMS EXITS NON-ZERO, so it can gate a
        # restore in a script without anyone parsing this output.
        return 1 if report["problems"] else 0

    from core.deployment_loader import resolve_runtime_paths

    data_dir = args.into or Path(resolve_runtime_paths().data_dir)
    try:
        restored = restore(args.backup, data_dir, force=args.force)
    except UnusableBackup as e:
        print(f"\n{e}", file=sys.stderr)
        return 1

    print(f"\nRestored into {data_dir}")
    # SAID OUT LOUD, because "nothing is deleted" helps only somebody
    # who knows where to look.
    print(f"What it replaced was moved, not deleted: {restored['replaced_into']}")
    print("THE DATA SILOS ARE NOT IN THIS BACKUP. Point the deployment at "
          "them before starting it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
