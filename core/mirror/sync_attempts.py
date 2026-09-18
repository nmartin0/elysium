"""What each sync attempt did, including the ones that failed.

WHY THIS EXISTS. The mirror's timestamps come from Iceberg snapshots,
which record when data last CHANGED. That is the right thing for them
to record, and it leaves two states indistinguishable from outside:

  a sync that ran and found nothing to do
  a sync that ran and was REFUSED

Both leave the previous snapshot in place. So a table whose syncs have
been failing since Tuesday looks exactly like one whose source has not
changed since Tuesday -- and the first is an incident while the second
is Tuesday.

SEEN ON A REAL DEPLOYMENT. The mirror panel showed a table last
changed two days ago while its sync had been refusing for two days on
a type change, and nothing on the screen could tell the two apart.

A SEPARATE STORE RATHER THAN TABLE PROPERTIES, which was the tempting
option because bronze already carries provenance there. A refused sync
may not reach bronze at all -- the refusal can happen while reading
the source -- so the one case this exists to record is the one that
could not be written.

SMALL AND PRUNED. One row per table per attempt, kept for a stated
window. A sync runs on a schedule measured in minutes at worst, and
nobody asks what happened six months ago; they ask what happened last
night.
"""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

# HOW LONG AN ATTEMPT IS WORTH KEEPING.
#
# Thirty days matches request_metrics' own retention, for the same
# reason: it covers "what happened last night" and "has this been
# failing all month" without keeping a year of noise. The two are
# unrelated stores and the number agreeing is a coincidence worth
# stating rather than a shared constant worth inventing.
RETENTION_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_attempts (
    at REAL NOT NULL,
    silo TEXT NOT NULL,
    table_name TEXT NOT NULL,
    -- 'synced', 'unchanged' or 'refused'. Three outcomes rather than a
    -- boolean, because "ran and did nothing" and "ran and was stopped"
    -- are the two this store exists to separate.
    outcome TEXT NOT NULL,
    -- Why, when it was refused. Null otherwise. The full drift report,
    -- because a reader who sees a refusal wants the column and the
    -- value, not a category.
    detail TEXT
);
-- Every read is "what happened to this table recently", so the pair is
-- the index. One on time alone would still scan a table's history.
CREATE INDEX IF NOT EXISTS sync_attempts_table_at
    ON sync_attempts (silo, table_name, at);
"""


@dataclass(frozen=True)
class SyncAttempt:
    """One attempt, as a reader sees it."""

    at: datetime
    silo: str
    table_name: str
    outcome: str
    detail: str | None


class SyncAttempts:
    """Records what each sync attempt did, and answers what happened.

    NEVER RAISES INTO THE SYNC. A sync whose data work succeeded must
    not fail because its bookkeeping did -- that would turn a working
    mirror into a broken one for the sake of a log. Failures are
    swallowed and reported, which is the same bargain bronze makes
    about its own provenance.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def record(self, silo: str, table_name: str, outcome: str,
               detail: str | None = None) -> None:
        """Records one attempt. Silent on failure -- see the class."""
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT INTO sync_attempts (at, silo, table_name, outcome, detail) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (time.time(), silo, table_name, outcome, detail),
                )
                # EXPLICIT, because open_connection sets
                # isolation_level='' -- an implicit transaction opens on
                # the first write and is ROLLED BACK on close unless
                # committed. A first version left this out and the rows
                # silently vanished: the table existed, the insert
                # reported success, and a fresh connection saw nothing.
                conn.commit()
        except Exception:  # noqa: BLE001 - see the class docstring
            return

    def last_for(self, silo: str, table_name: str) -> SyncAttempt | None:
        """The most recent attempt against one table, or None."""
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT at, outcome, detail FROM sync_attempts "
                    "WHERE silo = ? AND table_name = ? ORDER BY at DESC LIMIT 1",
                    (silo, table_name),
                ).fetchone()
        except Exception:  # noqa: BLE001 - see the class docstring
            return None

        if row is None:
            return None
        return SyncAttempt(
            at=datetime.fromtimestamp(row["at"], tz=UTC),
            silo=silo,
            table_name=table_name,
            outcome=row["outcome"],
            detail=row["detail"],
        )

    def forget_older_than(self, days: int = RETENTION_DAYS) -> int:
        """Drops attempts nobody will ask about. Returns how many."""
        cutoff = time.time() - days * 86400
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM sync_attempts WHERE at < ?", (cutoff,),
                )
                conn.commit()
                return cursor.rowcount
        except Exception:  # noqa: BLE001 - see the class docstring
            return 0
