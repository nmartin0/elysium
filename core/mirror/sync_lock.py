"""The lock that keeps two writers off the mirror at once.

WHY IT LIVES HERE RATHER THAN IN run_sync (PA001-A16). It was a
private helper of the sync script, and `repair_catalog --write`
REPOINTS TABLES IN THE SAME CATALOG without taking it -- so a repair
could land between a sync's read and its commit, and PyIceberg
surfaces that as a hard failure its retry loop cannot resolve.

Two callers is the moment a private helper becomes a shared one. The
reasoning below is the sync's original and is unchanged.
"""

import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def single_writer(lock_path: Path):
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
