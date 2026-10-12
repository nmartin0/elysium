"""Reclaims data files no Iceberg snapshot references (R11).

    python -m scripts.remove_orphan_files            # report only
    python -m scripts.remove_orphan_files --write    # delete them

Snapshot expiry UNREFERENCES files and pyiceberg has nothing that
deletes them (apache/iceberg-python #3361), so a mirror grows by about
one file per table per sync for ever -- measured, see
core/mirror/integrity.py. This is Iceberg's own `remove_orphan_files`
procedure for a local warehouse, with its two safeguards: only files
older than a margin (three days by default, Iceberg's), and only files
no snapshot anywhere in a table's history references.

HOLDS THE SYNC LOCK, so nothing is being written while it decides, and
REPORTS BY DEFAULT. A deletion against a lake gets a dry run first.

LOCAL WAREHOUSES ONLY. Object storage has its own lifecycle rules and
its own durability story; a warehouse on S3 is refused, not guessed at.
"""

import argparse
import sys

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.mirror.catalog import open_mirror_catalog
from core.mirror.integrity import ORPHAN_MARGIN_HOURS, orphaned_data_files
from core.mirror.sync_lock import single_writer


def run(paths=None, write: bool = False,
        older_than_hours: float = ORPHAN_MARGIN_HOURS) -> int:
    paths = paths or resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    if dict(config.mirror_storage).get("warehouse"):
        print("The warehouse is not local; use the object store's own lifecycle "
              "rules. Nothing was touched.")
        return 1
    mirror_dir = paths.data_dir / "mirror"
    catalog = open_mirror_catalog(mirror_dir, dict(config.mirror_storage))
    tables = {".".join(parts) for namespace in catalog.list_namespaces()
              for parts in catalog.list_tables(namespace)}

    with single_writer(paths.data_dir / "sync.lock") as acquired:
        if not acquired:
            print("A sync is running. Try again when it has finished; nothing was touched.")
            return 1
        found = orphaned_data_files(catalog, mirror_dir / "warehouse", tables,
                                    older_than_hours)
        total = sum(path.stat().st_size for paths_ in found.values() for path in paths_)
        for identifier, files in found.items():
            print(f"{identifier}: {len(files)} orphaned file(s)")
            if write:
                for path in files:
                    path.unlink()
        verb = "removed" if write else "would remove (dry run; --write to delete)"
        print(f"{verb}: {sum(len(f) for f in found.values())} file(s), {total // 1024} KB, "
              f"older than {older_than_hours:g} hours")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--write", action="store_true", help="delete; without it, report")
    parser.add_argument("--older-than-hours", type=float, default=ORPHAN_MARGIN_HOURS,
                        help=f"the safety margin (default {ORPHAN_MARGIN_HOURS}, Iceberg's)")
    args = parser.parse_args()
    return run(write=args.write, older_than_hours=args.older_than_hours)


if __name__ == "__main__":
    sys.exit(main())
