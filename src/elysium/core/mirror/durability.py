"""Forcing the mirror's own files to disk.

WHY THIS EXISTS, and it is not hypothetical: this deployment hit the
failure during development. The disk filled mid-sync, and afterwards
the catalog pointed at metadata file 00008 while only 00007 existed on
disk. `scripts/repair_catalog.py` was written to recover from it.

THE ORDERING IS EXACTLY BACKWARDS BY DEFAULT. pyiceberg writes
metadata through an unsynced path -- verified, the string "fsync"
appears nowhere in its pyarrow IO or table modules -- while SQLite
fsyncs its own commit. So the POINTER is made durable and the thing it
points at is not.

A crash therefore strands a table rather than losing a commit, which
is the worse of the two outcomes: losing the last sync is recoverable
by syncing again, and a pointer into nothing is not recoverable at all
without surgery.

TWO FSYNCS, NOT ONE. Flushing the file makes its CONTENTS durable; the
directory ENTRY naming it is a separate write in the parent directory,
and without syncing that too the file can exist with no name after a
crash.

NEVER RETRY A FAILED FSYNC. On Linux a failed fsync may clear the
error state, so a second call can report success while the data is
still lost -- the "fsyncgate" behaviour that cost PostgreSQL a
well-known post-mortem. A failure here is reported and the sync stops.

THIS NARROWS A WINDOW RATHER THAN CLOSING IT. Consumer SSDs may
acknowledge a flush before the data reaches NAND, so a power cut can
still lose an acknowledged write. That is a property of the hardware
and no amount of care in this file changes it.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class MirrorDurabilityError(OSError):
    """A file the mirror just wrote could not be forced to disk.

    ITS OWN TYPE, so a caller can tell "the disk would not take this"
    from the many other OSErrors a sync can raise. The distinction
    matters because this one means the mirror may now be INCONSISTENT
    rather than merely incomplete.
    """


def force_to_disk(path: Path) -> None:
    """Makes one file durable, contents and directory entry both.

    RAISES RATHER THAN WARNING. A sync that continues after this failed
    would commit a pointer to data that may not survive a crash, which
    is the exact failure this exists to prevent.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError as e:
        raise MirrorDurabilityError(
            f"{path}: could not be opened to force to disk: {e}"
        ) from e

    try:
        os.fsync(fd)
    except OSError as e:
        # NOT RETRIED. See the module docstring: a second fsync may
        # report success after the first failed, because the error
        # state has already been cleared.
        raise MirrorDurabilityError(
            f"{path}: could not be forced to disk: {e}. The mirror may be "
            f"inconsistent; do not treat this sync as committed."
        ) from e
    finally:
        os.close(fd)

    _force_directory_entry(path.parent)


def _force_directory_entry(directory: Path) -> None:
    """Makes the NAME durable, not just the contents.

    A file's data and the directory entry pointing at it are separate
    writes. Syncing only the file can leave it present with no name
    after a crash, which reads as a missing file rather than a corrupt
    one.
    """
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError as e:
        raise MirrorDurabilityError(
            f"{directory}: could not be opened to force its entries to "
            f"disk: {e}"
        ) from e

    try:
        os.fsync(fd)
    except OSError as e:
        raise MirrorDurabilityError(
            f"{directory}: directory entries could not be forced to disk: "
            f"{e}. The mirror may be inconsistent."
        ) from e
    finally:
        os.close(fd)


def force_table_metadata_to_disk(warehouse: Path, identifier: str) -> int:
    """Forces every metadata file of one table, newest first.

    RETURNS HOW MANY WERE SYNCED, which is the only honest measure of
    what this did: the caller cannot otherwise tell a table with no
    metadata from one where the sync silently matched nothing.

    EVERY FILE, NOT JUST THE NEWEST. Identifying "the current one"
    means parsing the catalog's pointer, and a mistake there syncs the
    wrong file while reporting success. The files are small and few --
    49 across four tables on the shipped deployment -- so syncing all
    of them costs little and cannot pick wrong.
    """
    namespace, _, table = identifier.partition(".")
    metadata_dir = warehouse / namespace / table / "metadata"
    if not metadata_dir.is_dir():
        # NOT AN ERROR. A table that has never been written has no
        # metadata directory, and a sync that creates one will force it
        # on the way through.
        return 0

    synced = 0
    for path in sorted(metadata_dir.iterdir(), reverse=True):
        if path.is_file():
            force_to_disk(path)
            synced += 1
    return synced
