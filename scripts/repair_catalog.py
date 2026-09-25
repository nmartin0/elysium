"""Repairs a catalog pointing at a metadata file that is not there.

WHAT GOES WRONG. Iceberg commits in two steps: write the new metadata
file, then swap the catalog's pointer to it. The order is correct in
pyiceberg -- verified by reading SqlCatalog.commit_table, which calls
_write_metadata before opening its database session -- and the spec's
own guarantee is that a crash "costs orphan data files rather than a
broken table".

THE GAP IS DURABILITY, NOT ORDER. pyiceberg writes the metadata
through `filesystem.open_output_stream(...)` and closes it. There is
no fsync anywhere in that path -- checked. A close() flushes to the
operating system; it does not force the data to disk. So when the disk
is full, or the machine loses power, the kernel can fail the writeback
AFTER close() returned successfully. The catalog then commits a
pointer to content that never landed.

That is not hypothetical. It happened to this project's own
development mirror when a container filled its disk: the catalog named
metadata file 00008 and only 00007 existed, and every read of the
table failed with FileNotFoundError.

RE-SYNCING CANNOT FIX IT, which is the part that makes this worth a
tool. Every write begins by reading the current snapshot, and the
current snapshot is the missing file, so a repair attempt fails for
the same reason the read does.

WHAT THIS DOES. Points the catalog back at the newest metadata file
that actually exists. The table becomes readable again, having lost
the commits recorded only in the missing file.

WHY THAT IS WORTH HAVING even though bronze and silver are derivable:
THE CHANGELOG IS NOT. A source holds "now" and cannot say what a value
used to be, so a changelog table lost this way loses history nothing
can rebuild. Deleting the mirror and re-syncing -- the obvious
recovery -- destroys exactly the one thing that cannot be recovered.

    python -m scripts.repair_catalog                 (report only)
    python -m scripts.repair_catalog --write         (repair)

REPORTS BY DEFAULT AND REPAIRS ONLY WHEN ASKED. Rewriting catalog
pointers is a destructive-adjacent act on the one file that makes a
warehouse readable, and a tool that did it on sight would be a worse
hazard than the fault it fixes.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

from core.deployment_loader import resolve_runtime_paths
from core.mirror.sync_lock import single_writer


def _metadata_path(location: str) -> Path:
    """The filesystem path a metadata_location refers to.

    LOCAL WAREHOUSES ONLY, and it says so rather than pretending. An
    s3:// location cannot be checked with Path.exists(), and a tool
    that silently reported every S3 table as broken would be worse than
    one that declines.
    """
    without_scheme = location.split("://", 1)[-1] if "://" in location else location
    return Path(without_scheme)


def find_broken(catalog_db: Path) -> list[tuple[str, str, str, list[Path]]]:
    """Tables whose pointer names a file that is not there.

    Returns the identifier, the dangling location, and the surviving
    metadata files, newest last.
    """
    broken = []
    connection = sqlite3.connect(catalog_db)
    try:
        rows = connection.execute(
            "SELECT table_namespace, table_name, metadata_location FROM iceberg_tables"
        ).fetchall()
    finally:
        connection.close()

    for namespace, name, location in rows:
        if location.startswith("s3://") or location.startswith("gs://"):
            # NOT CHECKABLE FROM HERE, and skipped loudly by the caller
            # rather than reported as healthy.
            continue
        path = _metadata_path(location)
        if path.exists():
            continue
        survivors = sorted(path.parent.glob("*.metadata.json"))
        broken.append((f"{namespace}.{name}", location, path.parent, survivors))

    return broken


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mirror", type=Path, default=None,
                        help="the mirror directory (default: the deployment's own)")
    parser.add_argument("--write", action="store_true",
                        help="actually repair, rather than only reporting")
    args = parser.parse_args()

    paths = resolve_runtime_paths()
    mirror_dir = args.mirror if args.mirror is not None else paths.data_dir / "mirror"
    catalog_db = mirror_dir / "catalog.db"

    if not catalog_db.exists():
        print(f"No catalog at {catalog_db}.", file=sys.stderr)
        return 1

    broken = find_broken(catalog_db)
    if not broken:
        print(f"Every catalog pointer in {mirror_dir} names a file that exists.")
        return 0

    print(f"{len(broken)} table(s) point at metadata that is not there:\n")
    repairable = []
    for identifier, location, _parent, survivors in broken:
        print(f"  {identifier}")
        print(f"    points at: {Path(location).name}")
        if survivors:
            print(f"    newest surviving: {survivors[-1].name}")
            repairable.append((identifier, survivors[-1]))
        else:
            # NOTHING TO FALL BACK TO. Said plainly, because this is the
            # case where the data is genuinely gone and a person needs
            # to know that rather than be offered a repair that cannot
            # work.
            print("    NO surviving metadata -- this table cannot be repaired here.")

    if not args.write:
        print(f"\nReporting only. Re-run with --write to repoint {len(repairable)} table(s).")
        print("Each repaired table loses the commits recorded only in the missing file.")
        return 1

    # THE SAME LOCK THE SYNC TAKES (PA001-A16). This repoints tables in
    # the catalog a sync writes to, and a repair landing between a
    # sync's read and its commit is exactly the race Iceberg's
    # optimistic concurrency turns into a hard failure -- the one
    # `single_writer` exists to prevent. It was a private helper of
    # run_sync, so this script simply did not take it.
    #
    # REFUSES RATHER THAN WAITS, like the sync: a repair is a
    # deliberate act by a person at a terminal, and "a sync is running,
    # try again" is a better answer than blocking for an unknown time
    # while they wonder whether it has hung.
    with single_writer(mirror_dir.parent / "sync.lock") as acquired:
        if not acquired:
            print("A sync is running. NOTHING WAS REPAIRED -- re-run when "
                  "it has finished.", file=sys.stderr)
            return 1
        return _repoint(catalog_db, repairable)


def _repoint(catalog_db: Path, repairable: list) -> int:
    connection = sqlite3.connect(catalog_db)
    try:
        for identifier, survivor in repairable:
            namespace, _, name = identifier.rpartition(".")
            connection.execute(
                "UPDATE iceberg_tables SET metadata_location = ? "
                "WHERE table_namespace = ? AND table_name = ?",
                (f"file://{survivor}", namespace, name),
            )
            print(f"  repointed {identifier} -> {survivor.name}")
        connection.commit()
    finally:
        connection.close()

    print("\nRun scripts.check_mirror to confirm, then re-sync to bring the")
    print("table up to date. Bronze and silver will rebuild; a changelog")
    print("will resume from where it was, having lost the last commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
