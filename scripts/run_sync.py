"""
run_sync.py  (copies the customer's own external data into Elysium's
local mirror -- one run, then exits)

Phase 2 of the read-only mirror architecture (see ROADMAP.md). A
SEPARATE PROCESS, deliberately, never a background thread inside the
web app -- a real, settled decision recorded in that section, for
three real reasons: it matches how every other entry point in
scripts/ already works; a sync copies entire tables, which would
otherwise compete with request handling in the same process (and
under the GIL, measurably slow it), while a badly-failing sync could
take the web server down with it; and it matches Foundry's own
precedent of running syncs as scheduled builds, separate from the
service answering queries.

This script performs ONE sync and exits. Scheduling is external and
deliberately not this script's concern -- a cron entry, a systemd
timer, a Kubernetes CronJob. Nothing here owns a timer or knows what
time it is beyond recording when a sync finished. That also means
"sync now" needs no special mechanism at all: running this script IS
the manual escape hatch.

WHAT IT SYNCS is derived entirely from the ontology itself (see
core/mirror/sync_targets.py), never from a second, separately-
maintained list -- so the mirror always holds exactly the tables the
ontology actually references, with no way for the two to drift apart.

READS THROUGH THE READ-ONLY ADAPTERS specifically (Phase 1 -- see
adapters/sqlite_adapter.py's own SQLiteReadAdapter), so this job is
structurally incapable of writing back to the customer's own data,
not merely intended not to.

FAILS LOUDLY, PER TABLE, leaving the last-good mirror in place for
whatever it couldn't sync -- matching this project's own established
"fail loudly, never silently substitute" discipline. A table that
fails does NOT abort the whole run: the other tables are genuinely
independent, and a partial refresh of the rest is strictly better
than none. Every failure is reported, and the process exits non-zero
so a scheduler actually notices rather than logging into the void.

Config and data are independent locations, resolved by
resolve_runtime_paths() exactly as every other entry point does --
this script never needs to know whether it is running locally or from
a real install.

Run from the project root:
    python3 -m scripts.run_sync
"""

import sys

from core.deployment_loader import load_deployment_bundle, resolve_runtime_paths
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets


def run_sync(runtime_paths=None) -> int:
    """Syncs every ontology-referenced table. Returns the number of
    tables that FAILED -- 0 meaning a fully successful run, so a
    caller (and __main__ below) can use it directly as an exit code."""
    if runtime_paths is None:
        runtime_paths = resolve_runtime_paths()

    # The read adapters specifically -- load_deployment_bundle()'s own
    # third return value is the WRITE set, deliberately ignored here.
    # A sync only ever reads from the source.
    config, mediator, _write_adapters = load_deployment_bundle(
        runtime_paths.config_dir, runtime_paths.data_dir
    )

    targets = resolve_sync_targets({"object_types": config.schema})
    sync = IcebergMirrorSync(runtime_paths.data_dir / "mirror", mediator.adapters)

    failures = 0
    for target in targets:
        label = f"{target.silo_name}.{target.table_name}"
        try:
            result = sync.sync_table(
                target.silo_name, target.table_name, target.id_column, target.columns
            )
        except Exception as exc:
            # Per-table, deliberately -- see this module's docstring.
            # The exception itself is printed rather than swallowed into
            # a generic message: this is an operator-facing tool, and
            # the real cause is exactly what an operator needs.
            failures += 1
            print(f"FAILED  {label}: {exc}", file=sys.stderr)
            continue
        print(f"synced  {label}: {result.row_count} rows at {result.synced_at.isoformat()}")

    print(f"\n{len(targets) - failures}/{len(targets)} tables synced successfully.")
    return failures


if __name__ == "__main__":
    sys.exit(run_sync())
