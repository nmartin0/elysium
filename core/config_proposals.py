"""Configuration changes waiting for a second person (decided 16 October).

WHICH ONES WAIT. A change to the configuration files that would let
anyone read, know of or run something they could not before -- asked of
the permission code, not of the edit's direction
(core/role_impact.config_access_impact). Two kinds arrive here: a field's
access labels (`classification:`), and an earlier version put back.
Everything else applies at once.

WHO DECIDES. A holder of manage:roles who is not the proposer: the
people who already approve role changes, because this IS a change to
who sees what by another route. Foundry likewise makes removing a
marking a power of its own ("the Expand Access permission on the
marking itself ... is required to remove a marking"), apart from owning
the data.

WHAT IS STORED IS THE FILES, whole, as they would be written -- and the
digest of each as it was when proposed. An approver agrees to exactly
those bytes. If a file has moved since (somebody edited it, another
proposal landed), approving is refused as STALE rather than merged: a
merge is a change nobody reviewed. The same rule as role changes.

A REASON, ALWAYS. Purview asks for a justification whenever a label is
lowered, "logged for auditing purposes"; here it is shown to the
approver as well, who is the person it is for.

THE TABLE IS THE RECORD: who proposed what and why, who decided, and how
it ended. Rows are never deleted.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.sqlite_connection import connection_with_schema

LABELS = "labels"
RESTORE = "restore"
KINDS = (LABELS, RESTORE)

#: The most a reason may say. It is read by a person deciding.
MAX_REASON = 500

SCHEMA = """
CREATE TABLE IF NOT EXISTS config_proposals (
    proposal_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    -- What it is, for a person: "Customer.email: pii removed",
    -- "Put generation 40 back".
    summary TEXT NOT NULL,
    -- {filename: the whole file as it would be written}
    files TEXT NOT NULL,
    -- {filename: digest of the file when proposed}
    base TEXT NOT NULL,
    reason TEXT NOT NULL,
    proposed_by TEXT NOT NULL,
    proposed_at TEXT NOT NULL,
    -- pending, applied, rejected, withdrawn, stale, or failed.
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by TEXT,
    decided_at TEXT,
    detail TEXT
);
"""


@dataclass(frozen=True)
class ConfigProposal:
    proposal_id: str
    kind: str
    summary: str
    files: dict[str, str]
    base: dict[str, str]
    reason: str
    proposed_by: str
    proposed_at: str
    status: str
    decided_by: str | None
    decided_at: str | None
    detail: str | None


class ConfigProposalStore:
    def __init__(self, db_path: Path):
        self._db_path = db_path

    def _connection(self):
        return connection_with_schema(self._db_path, SCHEMA)

    def propose(self, kind: str, summary: str, files: dict[str, str], base: dict[str, str],
                reason: str, proposed_by: str) -> str:
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        proposal_id = str(uuid.uuid4())
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO config_proposals (proposal_id, kind, summary, files, base, reason, "
                "proposed_by, proposed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (proposal_id, kind, summary, json.dumps(files), json.dumps(base), reason,
                 proposed_by, datetime.now(UTC).isoformat()),
            )
            conn.commit()
        return proposal_id

    def get(self, proposal_id: str) -> ConfigProposal | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM config_proposals WHERE proposal_id = ?",
                               (proposal_id,)).fetchone()
        return _row(row) if row else None

    def pending(self) -> list[ConfigProposal]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM config_proposals WHERE status = 'pending' "
                                "ORDER BY proposed_at").fetchall()
        return [_row(row) for row in rows]

    def decide(self, proposal_id: str, status: str, decided_by: str,
               detail: str | None = None) -> bool:
        """How a proposal ended. Only a PENDING one can end -- `AND status
        = 'pending'` in the update, so two approvers at once cannot both."""
        with self._connection() as conn:
            changed = conn.execute(
                "UPDATE config_proposals SET status = ?, decided_by = ?, decided_at = ?, "
                "detail = ? WHERE proposal_id = ? AND status = 'pending'",
                (status, decided_by, datetime.now(UTC).isoformat(), detail, proposal_id),
            ).rowcount
            conn.commit()
        return changed == 1


def _row(row) -> ConfigProposal:
    return ConfigProposal(
        proposal_id=row["proposal_id"], kind=row["kind"], summary=row["summary"],
        files=json.loads(row["files"]), base=json.loads(row["base"]), reason=row["reason"],
        proposed_by=row["proposed_by"], proposed_at=row["proposed_at"], status=row["status"],
        decided_by=row["decided_by"], decided_at=row["decided_at"], detail=row["detail"],
    )
