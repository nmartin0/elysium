"""Where pending writes live, and the only place they live.

THE DATABASE IS THE STORE, not a mirror of one. This module used to
describe itself as WRITE-THROUGH: the store kept a locked dict as the
truth and mirrored each mutation here, reading this file only at
startup. That made the queue survive a restart and left it invisible
to a SECOND PROCESS -- a sync started by cron, proposing a write the
running API would never see.

Every SQLite-backed queue worth copying puts it the other way: "the
database is still the source of truth". So `PendingWriteStore` now
reads and writes here directly, and this module holds only what the
database IS -- where it lives and what its tables look like.

A RESTORED WRITE IS STILL A PROPOSAL, NOT AN APPROVAL. Everything
about whether it may execute is asked again at confirm time, against
the CURRENT configuration. Nothing here grants anything.

NO LONGER BEST-EFFORT, and that is the one behaviour that changed on
purpose. When memory was the truth, a proposal that could not reach
disk was still a proposal. Now there is no other copy: a write that
cannot be stored does not exist, and the caller must hear so rather
than being told it was queued.
"""

from pathlib import Path

from core.sqlite_connection import add_column_if_missing, connection_with_schema

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_writes (
    write_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    payload TEXT NOT NULL,
    -- HELD BY SOMEBODY DECIDING ON IT. Claimed with
    -- `UPDATE ... SET reserved = 1 WHERE write_id = ? AND reserved = 0`,
    -- which either takes the row or matches nothing because somebody
    -- else already did -- across threads AND processes, because SQLite
    -- serialises writers.
    reserved INTEGER NOT NULL DEFAULT 0
);
-- Every read is "what is still pending", and expiry is how a row
-- leaves. One index on the only column anyone filters by.
CREATE INDEX IF NOT EXISTS pending_writes_expires_at
    ON pending_writes (expires_at);

CREATE TABLE IF NOT EXISTS pending_write_decisions (
    write_id TEXT NOT NULL,
    task_index INTEGER NOT NULL,
    approver_user_id TEXT NOT NULL,
    approved INTEGER NOT NULL,
    decided_at TEXT NOT NULL,
    PRIMARY KEY (write_id, task_index)
);
"""


class PendingWritePersistence:
    """The database a PendingWriteStore reads and writes.

    A LOCATION, not a behaviour. The store does all the SQL; this
    exists so the app can say where the queue lives and every process
    that opens it agrees on the schema.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def connection(self):
        # MIGRATED, because a pending_writes.db from before `reserved`
        # existed would otherwise fail every claim with "no such
        # column" -- the saved-views bug, again, in the table under the
        # approvals queue.
        return connection_with_schema(
            self._db_path, SCHEMA,
            migrations=(
                add_column_if_missing(
                    "pending_writes", "reserved", "INTEGER NOT NULL DEFAULT 0",
                ),
            ),
        )
