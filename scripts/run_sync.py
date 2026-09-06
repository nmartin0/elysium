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

import fcntl
import sys
from contextlib import contextmanager
from pathlib import Path

from core.deployment_loader import load_deployment_bundle, resolve_runtime_paths
from core.mirror.iceberg_sync import IcebergMirrorSync
from core.mirror.sync_targets import resolve_sync_targets
from core.sqlite_connection import require_assertions_enabled


@contextmanager
def _single_writer(lock_path: Path):
    """Holds an exclusive lock for the duration of a sync, or yields
    False if another sync already holds it.

    Iceberg uses optimistic concurrency: a commit carries "the table's
    metadata is version N", and a second writer that started from the
    same N is rejected rather than allowed to clobber the first. That
    design is correct -- it is what prevents a lost overwrite. But
    PyIceberg surfaces the rejection as a hard exception its retry loop
    cannot resolve for a full-table overwrite (Java Iceberg retries
    transparently; PyIceberg's equivalent is still open upstream).
    Confirmed by running two syncs at once: one committed, the other
    failed with "Added data files were found matching the filter".

    Genuinely reachable rather than hypothetical -- INSTALL.md tells
    operators to schedule syncs with cron or a systemd timer, and
    nothing stops a slow run from overlapping the next scheduled one.

    flock rather than a PID file: it is released automatically when the
    process dies, so a crash leaves nothing stale to clean up.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def run_sync(runtime_paths=None) -> int:
    """Syncs every ontology-referenced table. Returns the number of
    tables that FAILED -- 0 meaning a fully successful run, so a
    caller (and __main__ below) can use it directly as an exit code."""
    # The sync has its own invariant asserts -- that the committed
    # snapshot holds exactly what was written -- so it needs the same
    # guarantee the server does.
    require_assertions_enabled()

    if runtime_paths is None:
        runtime_paths = resolve_runtime_paths()

    with _single_writer(runtime_paths.data_dir / "sync.lock") as acquired:
        if not acquired:
            # Exits rather than waiting: the run this collided with is
            # already copying the same data, so queueing would only
            # duplicate work. Exit code 0 -- a skipped run is a normal
            # outcome, not something a scheduler should alert on.
            print(
                "another sync is already running -- exiting without doing anything",
                file=sys.stderr,
            )
            return 0

        # The read adapters specifically -- load_deployment_bundle()'s
        # own third return value is the WRITE set, deliberately ignored
        # here. A sync only ever reads from the source.
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
                    target.silo_name, target.table_name, target.id_column,
                    target.columns, target.column_types,
                )
            except Exception as exc:
                # Per-table, deliberately -- see this module's docstring.
                # The exception itself is printed rather than swallowed
                # into a generic message: this is an operator-facing
                # tool, and the real cause is what an operator needs.
                failures += 1
                print(f"FAILED  {label}: {exc}", file=sys.stderr)
                continue
            print(f"synced  {label}: {result.row_count} rows at {result.synced_at.isoformat()}")

        print(f"\n{len(targets) - failures}/{len(targets)} tables synced successfully.")
        return failures


if __name__ == "__main__":
    sys.exit(run_sync())
