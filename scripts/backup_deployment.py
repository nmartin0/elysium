"""Capture a running deployment's own state, consistently.

    python -m scripts.backup_deployment /path/to/backup.elysium-backup
    python -m scripts.backup_deployment --check
    python -m scripts.backup_deployment --new-key /somewhere/else/backup.key
    python -m scripts.backup_deployment --unencrypted /path/to/backup-dir

ENCRYPTED BY DEFAULT (decided 14 Oct). A backup exists to be copied off
the machine, which is exactly where volume encryption stops protecting
it. So the backup is one file, sealed with AES-256-GCM under a fresh
data key that is itself wrapped by the key in ELYSIUM_BACKUP_KEY_FILE
(core/encrypted_archive.py). The key file must live outside both the
data directory and the backup's destination -- a key kept with what it
protects protects nothing -- and is refused otherwise. An unencrypted
directory is still available, but only by saying --unencrypted.

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
import os
import shutil
import sqlite3
import sys
import tempfile
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
    # THE RULES THAT WARNED AND LET THE ROW THROUGH. Backed up rather
    # than excluded, for the reason sync_attempts beside it is: the
    # NEXT sync re-derives what is warning now, but not what was
    # warning last week. "Has this been firing all month" is a question
    # about the thirty-day window this store keeps, and a restore that
    # silently emptied it would answer "no" for a month.
    #
    # Small by construction -- counts per rule per run, and nothing at
    # all written for a clean run.
    "mirror/expectation_warnings.db",
    # COLUMN PROFILES, one per publication (R7). The series IS the
    # check: a restore that emptied it would make the next publication
    # the first, and drift would go unmeasured until the one after.
    "mirror/column_profiles.db",
    # Frozen sets: who was in a set at an instant. Not derivable from
    # anything else -- the membership is the record.
    "frozen_sets.db",
    # THE ERASURE REGISTER (R13): salted hashes of who was forgotten,
    # never their ids. Backed up so a restore onto a fresh machine still
    # knows; and a restore over a live deployment keeps the NEWER copy
    # (restore_deployment._keep_every_erasure), since it only grows.
    "erasures.db",
    # The approvals queue -- database-authoritative since patch 276,
    # so there is no other copy of a waiting decision.
    "pending_writes.db",
    # THE QUESTIONS THOSE WRITES PAUSED (WIRED-2), kept beside them: a
    # restore that brought back a waiting write without its question
    # would approve it and never answer the person who asked.
    "paused_queries.db",
    # WHAT PEOPLE ASKED TO HAVE REMEMBERED about objects (E-14). Written
    # by hand, one sentence at a time; there is no other copy.
    "memories.db",
    # A PERSON'S JUDGEMENT ON EACH CLEANING SUGGESTION (R31). Losing it
    # would raise every dismissed "N/A" again.
    "rule_suggestions.db",
    # THE JUDGEMENTS A PERSON MADE ABOUT WHO IS WHO (GOLD-6). Nothing
    # upstream remembers them: gold is rebuilt from silver on every
    # sync, and the merges it applies exist ONLY here. Losing this file
    # would silently un-merge every entity somebody had approved, and
    # the next sync would publish the un-merged version without
    # complaint. The backup guard caught it the moment the store
    # appeared, which is what that guard is for.
    "identity_decisions.db",
    # WHICH SOURCE HELD WHEN TWO DISAGREED (R60). Not rebuildable: an
    # ended disagreement is recognised by comparing its last conflict
    # row with what both sources hold NOW, so once they move on again
    # the evidence exists only here. The backup guard caught it.
    "source_record.db",
    "saved_views.db",
    # WHERE EACH PERSON PUT THE TYPES, AND THEIR SUBJECT AREAS (DEV_UI
    # 14). Presentation, but their own work: an arrangement built by
    # dragging forty types is an afternoon nobody wants to repeat. The
    # backup guard caught it the moment the store appeared.
    "canvas_layouts.db",
    # WHAT A PERSON APPROVED A MODEL'S RULES TO ANSWER (R41). The only
    # record of the approvals that decide what enriched fields hold;
    # losing it empties every one of them at the next sync.
    "enrichment_recipes.db",
    # WHAT A PERSON APPROVED A MODEL TO PREDICT, PER COMPARTMENT (R48).
    # No model is kept -- the sync retrains -- so this is the only record
    # of the approvals; losing it empties every predicted field.
    "prediction_proposals.db",
    "triggers.db",
    # VECTORS FOR SEARCH BY MEANING (R45). Derivable from gold, but a
    # first pass on a CPU can take hours, so a restore should not have
    # to pay it again. As sensitive as the text they came from --
    # backups are encrypted (core/encrypted_archive.py).
    "embeddings.db",
    # WHAT IS WAITING TO HAPPEN AT A TIME (16 October). A date-filtered
    # trigger's timer would be rebuilt when the server starts, but the
    # store is for any caller, and a later one may not be derivable.
    # Restoring an old timer is harmless: every handler re-checks.
    "timers.db",
    "notifications.db",
    # ONCE SOMEBODY EDITS A ROLE, THE ONLY COPY OF THE GRANTS. Losing it
    # on restore would silently fall back to policy.yaml -- restoring
    # every grant that had been deliberately withdrawn. The backup
    # guard caught this the moment the store was written.
    "roles.db",
    # CONFIGURATION CHANGES WAITING FOR A SECOND PERSON (DEV_UI 13.7):
    # who asked for which labels to come off, and why. The only copy of
    # a waiting decision, like pending_writes.db.
    "config_proposals.db",
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


KEY_VARIABLE = "ELYSIUM_BACKUP_KEY_FILE"


def backup_encrypted(data_dir: Path, destination: Path, key_file: Path) -> dict:
    """A backup as one sealed file. The plain snapshot is staged in a
    private temporary directory on this machine -- whose volume is the
    one that is meant to be encrypted -- and removed afterwards."""
    from core.encrypted_archive import encrypt_directory, read_key_file

    destination = Path(destination)
    kek = read_key_file(key_file, must_not_be_under=(data_dir, destination.parent))
    staging = Path(tempfile.mkdtemp(prefix="elysium-backup-"))
    try:
        result = backup(data_dir, staging)
        sealed = encrypt_directory(staging, destination, kek)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {**result, **sealed, "file": str(destination)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("destination", type=Path, nargs="?",
                        help="the backup file to write (a directory with --unencrypted)")
    parser.add_argument("--check", action="store_true",
                        help="report what WOULD be captured, and write nothing")
    parser.add_argument("--unencrypted", action="store_true",
                        help="write a plain directory instead of an encrypted file")
    parser.add_argument("--new-key", type=Path, metavar="PATH",
                        help="write a new random backup key to PATH (owner-only) and stop")
    args = parser.parse_args()

    if args.new_key:
        from core.encrypted_archive import write_key_file

        write_key_file(args.new_key)
        print(f"wrote a new backup key to {args.new_key}. Keep it OUTSIDE the data directory "
              f"and away from the backups, and keep a copy somewhere safe: without it a "
              f"backup cannot be restored.\nThen: export {KEY_VARIABLE}={args.new_key}")
        return 0

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

    if args.destination is None:
        parser.error("a destination is required")
    if args.unencrypted:
        result = backup(data_dir, args.destination)
        print("UNENCRYPTED, as asked: anyone who obtains this directory can read everything "
              "the mirror holds.")
    else:
        key_file = os.environ.get(KEY_VARIABLE)
        if not key_file:
            print(f"Backups are encrypted, and {KEY_VARIABLE} names no key. Make one with\n"
                  f"    python -m scripts.backup_deployment --new-key /somewhere/else/backup.key\n"
                  f"or pass --unencrypted to write a plain directory.", file=sys.stderr)
            return 1
        from core.encrypted_archive import ArchiveKeyError

        try:
            result = backup_encrypted(data_dir, args.destination, Path(key_file))
        except ArchiveKeyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"encrypted with key {result['key_id']} into {result['file']} "
              f"({result['bytes']:,} bytes)")
    print(f"captured {len(result['captured'])} database(s) and "
          f"{result['warehouse_files']} warehouse file(s)")
    if result["absent"]:
        # NOT A FAILURE, and not silent either. A young deployment
        # genuinely lacks the lazily-created ones.
        print(f"absent (not yet created): {', '.join(result['absent'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
