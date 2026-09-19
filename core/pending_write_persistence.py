"""Where pending writes live across a restart.

THE PRODUCT CLAIM THIS DEFENDS. Elysium's pitch is that writes are
mediated and approved. Losing the approval queue on deploy is the
worst possible fit between that claim and the behaviour -- and the
store's own docstring said so plainly, as a stated limitation rather
than an oversight.

WRITE-THROUGH, NOT A REPLACEMENT. PendingWriteStore keeps its locked
dict as the working store and mirrors every mutation here. Reads
answer from memory; only restarts read from disk.

A RESTORED WRITE IS A PROPOSAL, NOT AN APPROVAL. Everything about
whether it may now execute is asked again at confirm time against the
CURRENT configuration. This module grants nothing and decides nothing.

BEST-EFFORT, DELIBERATELY. A failure to persist is logged and the
in-memory store carries on: a proposal that cannot be written to disk
is still a proposal somebody made, and refusing it would turn a
storage problem into a service outage. The failure mode this accepts
is losing that one write on a restart, which is exactly what happens
today for all of them.
"""

import logging
from datetime import UTC, datetime
from pathlib import Path

from core.ontology.write_mediator import PendingWrite
from core.pending_write_serialisation import (
    UnreadablePendingWrite,
    from_row,
    to_row,
)
from core.sqlite_connection import connection_with_schema

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_writes (
    write_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    payload TEXT NOT NULL
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
    """Mirrors the pending-write store to SQLite."""

    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def record(self, write_id: str, stored) -> None:
        """Mirrors one newly stored write. Silent on failure."""
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO pending_writes "
                    "(write_id, owner_user_id, expires_at, payload) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        write_id,
                        stored.owner_user_id,
                        stored.expires_at.isoformat(),
                        to_row(stored.pending),
                    ),
                )
                # EXPLICIT, because open_connection sets
                # isolation_level='' -- an implicit transaction opens on
                # the first write and is ROLLED BACK on close unless
                # committed. sync_attempts.py learned this the hard way:
                # the table existed, the insert reported success, and a
                # fresh connection saw nothing.
                conn.commit()
        except Exception as e:  # noqa: BLE001 - see the module docstring
            logger.warning("could not persist pending write %s: %s", write_id, e)

    def forget(self, write_id: str) -> None:
        """Removes a write that has been decided or has expired."""
        try:
            with self._connection() as conn:
                conn.execute(
                    "DELETE FROM pending_writes WHERE write_id = ?", (write_id,),
                )
                conn.execute(
                    "DELETE FROM pending_write_decisions WHERE write_id = ?",
                    (write_id,),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001 - see the module docstring
            logger.warning("could not forget pending write %s: %s", write_id, e)

    def record_decision(self, write_id: str, task_index: int, approval) -> None:
        """Mirrors one per-task decision."""
        try:
            with self._connection() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO pending_write_decisions "
                    "(write_id, task_index, approver_user_id, approved, decided_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        write_id, task_index, approval.approver_user_id,
                        1 if approval.approved else 0,
                        approval.decided_at.isoformat(),
                    ),
                )
                conn.commit()
        except Exception as e:  # noqa: BLE001 - see the module docstring
            logger.warning(
                "could not persist decision on %s task %d: %s",
                write_id, task_index, e,
            )

    def load(self) -> list[tuple[str, str, datetime, PendingWrite, dict]]:
        """Everything still pending, as (id, owner, expires_at, pending,
        decisions).

        ONE UNREADABLE ROW COSTS ITS OWN WRITE, not the queue. A
        restart that dropped every pending approval because one was
        written by an older build would be worse than the problem being
        solved.

        EXPIRED ROWS ARE NOT RETURNED. A write whose TTL passed while
        the service was down has expired as surely as one that expired
        while it was up.
        """
        try:
            with self._connection() as conn:
                rows = conn.execute(
                    "SELECT write_id, owner_user_id, expires_at, payload "
                    "FROM pending_writes",
                ).fetchall()
                decisions = conn.execute(
                    "SELECT write_id, task_index, approver_user_id, approved, "
                    "decided_at FROM pending_write_decisions",
                ).fetchall()
        except Exception as e:  # noqa: BLE001 - see the module docstring
            logger.warning("could not read persisted pending writes: %s", e)
            return []

        by_write: dict[str, dict] = {}
        for row in decisions:
            by_write.setdefault(row["write_id"], {})[row["task_index"]] = {
                "approver_user_id": row["approver_user_id"],
                "approved": bool(row["approved"]),
                "decided_at": datetime.fromisoformat(row["decided_at"]),
            }

        now = datetime.now(UTC)
        restored = []
        for row in rows:
            expires_at = datetime.fromisoformat(row["expires_at"])
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if now >= expires_at:
                continue
            try:
                pending = from_row(row["payload"])
            except UnreadablePendingWrite as e:
                logger.warning(
                    "dropping persisted write %s: %s", row["write_id"], e,
                )
                continue
            restored.append((
                row["write_id"], row["owner_user_id"], expires_at, pending,
                by_write.get(row["write_id"], {}),
            ))
        return restored
