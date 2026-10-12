"""Every version of a source row, as SCD Type 2 (R10).

    python -m scripts.history_of primary_sql.customers            # all rows
    python -m scripts.history_of primary_sql.customers cust_001   # one

Reads the changelog the sync keeps for a source table and prints each
version of each row with when it became current and when it stopped --
Kimball's Type 2 -- as CSV, so it opens in anything. The clock is when
the sync NOTICED: a snapshot diff cannot know when the source changed.
A version the changelog never saw begin shows an empty valid_from.
"""

import csv
import sys

from core.deployment_loader import load_deployment, resolve_runtime_paths
from core.mirror.catalog import open_mirror_catalog
from core.mirror.changelog import scd2_versions
from core.mirror.sync_targets import resolve_sync_targets


def run(table: str, object_id: "str | None" = None, paths=None, out=sys.stdout) -> int:
    paths = paths or resolve_runtime_paths()
    config = load_deployment(paths.config_dir)
    silo, _, table_name = table.partition(".")
    target = next((t for t in resolve_sync_targets({"object_types": config.schema})
                   if t.silo_name == silo and t.table_name == table_name), None)
    if target is None:
        print(f"{table} is not a table this deployment syncs.", file=sys.stderr)
        return 1
    catalog = open_mirror_catalog(paths.data_dir / "mirror", dict(config.mirror_storage))
    try:
        entries = catalog.load_table(f"changelog_{silo}.{table_name}").scan().to_arrow().to_pylist()
    except Exception:  # noqa: BLE001 - no changelog yet is an answer, not a crash
        print(f"No changelog for {table} yet: it is written from the second sync on.",
              file=sys.stderr)
        return 1
    versions = scd2_versions(entries, target.id_column)
    if object_id is not None:
        versions = [v for v in versions if str(v.get(target.id_column)) == object_id]
    columns = [*target.columns, "_valid_from", "_valid_to", "_current"]
    writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(versions)
    return 0


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(run(sys.argv[1], sys.argv[2] if len(sys.argv) == 3 else None))
